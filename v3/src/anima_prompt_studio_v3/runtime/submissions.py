"""Accept once in SQLite, then deliver frozen jobs to the execution queue."""
from __future__ import annotations

import secrets
from copy import deepcopy
import logging
import sqlite3
from threading import Event, Thread
from uuid import uuid4

from anima_prompt_studio.domain.execution_models import GenerationRun
from anima_prompt_studio.domain.models import PromptJob
from ..api.workspace_store import WorkspaceRevisionConflictError
from ..core.requirements import PromptEdit, RequirementLora, WorkbenchError, compile_state, digest
from ..storage.generation_submissions import SubmissionStore, IdempotencyConflict
from .generation import PreparedGeneration
from .workflow_catalog import fingerprint


def payload_digest(payload, endpoint):
    return digest({"endpoint": endpoint, "payload": payload.model_dump(mode="json", by_alias=True)})


class SubmissionService:
    def __init__(self, workspaces, queue, response_factory, *, start=True):
        self.store = SubmissionStore(workspaces)
        self.queue = queue
        self.reference_get = None
        self.response_factory = response_factory
        self.wake, self.stopping = Event(), Event()
        for entry in self.store.list():
            queue.restore_durable(entry)
        queue.on_durable_cancel = lambda sid: self.store.mark(sid, "canceled")
        self.worker = Thread(target=self._loop, name="anima-submission-dispatch", daemon=True)
        if start:
            self.worker.start()
            self.wake.set()

    def submit(self, payload, key, endpoint, prepare):
        key = key.strip()
        if not key or len(key) > 256:
            raise WorkbenchError("invalid_request", "幂等键必须是 1–256 个字符。")
        request_hash = payload_digest(payload, endpoint)
        old = self.store.lookup(key, request_hash)
        if old:
            return old["response"]
        existing = self.queue.existing_request(key, request_hash)
        if existing is not None:
            if existing.request_json.get("submission_id"):
                accepted = self.store.lookup(key, request_hash)
                if accepted is None:
                    raise IdempotencyConflict("提交回执缺失，请检查原任务。")
                return accepted["response"]
            return self.response_factory(existing)
        reference = None
        if payload.submission_kind == "reference":
            if self.reference_get is None:
                raise WorkbenchError("reference_preset_not_found", "参考目录尚未接入。")
            reference = deepcopy(self.reference_get(payload.reference_preset_id, payload.source_version))
            if not reference["requirements_valid"]:
                raise WorkbenchError("empty_requirements", "参考图尚无有效要求。")
        workspace = None
        if payload.submission_kind == "conversational":
            workspace = self.store.workspaces.get(payload.workspace_id)
            if workspace["revision"] != payload.workspace_revision:
                raise WorkspaceRevisionConflictError(workspace["revision"])
            draft = workspace["draft"]
            if (not draft["compiled"] or draft["compiled"]["compiled_token"] != payload.compiled_token
                    or compile_state(draft) != "fresh"):
                raise WorkbenchError("stale_compiled_prompt", "要求或编译版本已变化，请重新编译。")
            resources = [RequirementLora.model_validate(item) for item in draft["requirements"]["loras"]]
        elif reference and "lora_selection" not in payload.model_fields_set:
            resources = [RequirementLora.model_validate(item) for item in reference["requirements"]["loras"] if item["required"]]
        else:
            resources = [RequirementLora.model_validate(item.model_dump()) for item in payload.lora_selection]
        prepared = prepare()
        if workspace and prepared.job.model_profile_id != workspace["draft"]["model_profile"]:
            raise WorkbenchError("stale_compiled_prompt", "请求模型与已编译的草稿不一致。")
        frozen = None
        if payload.workflow_snapshot_run_id:
            from .generation_queue import GenerationRunNotFoundError
            try:
                run = self.queue.get(payload.workflow_snapshot_run_id)
            except GenerationRunNotFoundError as exc:
                raise WorkbenchError("workflow_snapshot_missing", "原任务没有可用工作流快照。") from exc
            frozen = run.request_json.get("workflow_snapshot")
            if not frozen:
                raise WorkbenchError("workflow_snapshot_missing", "原任务没有可用工作流快照。")
        prepared, target, resolution = self.queue.plan(prepared, payload.remote_profile_id,
                                                      payload.workflow_profile_id, resources, frozen)
        compat = (reference["compat"] if reference else workspace["draft"]["reference_pin"]["source_snapshot"]["compat"]
                  if workspace and workspace["draft"]["reference_pin"] else None)
        if compat:
            if (compat["model_profiles"] and prepared.job.model_profile_id not in compat["model_profiles"]
                    or compat["workflow_kinds"] and target.workflow_profile.workflow_kind not in compat["workflow_kinds"]):
                raise WorkbenchError("reference_preset_unavailable", "当前目标不符合已钉选来源的兼容声明。")
        if prepared.job.generation_params.seed == -1:
            prepared.job.generation_params.seed = secrets.randbelow(2**63)
        sid = "sub_" + uuid4().hex
        run = GenerationRun(prompt_job_id=prepared.job.id, remote_profile_id=payload.remote_profile_id,
                            workflow_profile_id=payload.workflow_profile_id, status_message="已接受，等待入队",
                            request_json={"submission_id": sid, "prompt_job": prepared.job.model_dump(mode="json"),
                                          "workflow_snapshot": target.workflow_profile.model_dump(mode="json"),
                                          "local_queue": {"idempotency_key": key, "payload_hash": request_hash}})
        snapshot = {"run": run.model_dump(mode="json"), "job": prepared.job.model_dump(mode="json"),
                    "checkpoint_logical_name": prepared.checkpoint_logical_name,
                    "remote_fingerprint": fingerprint(target.remote_profile),
                    "workflow": target.workflow_profile.model_dump(mode="json"),
                    "resources": [r.model_dump(mode="json") for r in resources], "resolution": resolution,
                    "provenance": {"requirements": None, "positive": prepared.job.positive_prompt,
                                   "negative": prepared.job.negative_prompt, "model_profile": prepared.job.model_profile_id,
                                   "settings": prepared.job.generation_params.model_dump(mode="json"),
                                   "loras": resolution["bindings"], "workflow_snapshot_ref": run.id}}
        response = {**self.response_factory(run), "submission_id": sid}
        if reference:
            origin = {"example_id": reference["id"], "source_version": reference["source_version"],
                      "source_snapshot": {"requirements": reference["requirements"], "compat": reference["compat"]}}
            actual_requirements = deepcopy(reference["requirements"])
            actual_resources = [item.model_dump(mode="json") for item in resources]
            if actual_requirements["loras"] != actual_resources:
                actual_requirements["loras"] = actual_resources
                actual_requirements["revision"] += 1
            snapshot.update(reference=origin, requirements=actual_requirements)
            snapshot["provenance"].update(reference=origin, requirements=actual_requirements)

        def accept():
            return self.store.accept(submission_id=sid, key=key, payload_hash=request_hash, run_id=run.id,
                                     snapshot=snapshot, response=response,
                                     workspace_id=workspace["id"] if workspace else None,
                                     revision=payload.workspace_revision if workspace else None,
                                     token=payload.compiled_token if workspace else None,
                                     prompt=PromptEdit(positive=prepared.job.positive_prompt, negative=prepared.job.negative_prompt))
        try:
            entry = self.queue.accept_durable(key, request_hash, accept)
        except IdempotencyConflict:
            old = self.store.lookup(key, request_hash)
            if old:
                return old["response"]
            raise
        self.wake.set()
        return entry["response"]

    def dispatch_pending(self):
        for entry in self.store.for_runs(self.queue.reserved_ids()):
            if self.stopping.is_set() or entry["dispatch_state"] not in {"accepted", "enqueued"}:
                continue
            run = self.queue.get(entry["run_id"])
            if not self.queue.is_reserved(run.id):
                continue
            snapshot = entry["snapshot"]
            try:
                prepared = PreparedGeneration(job=PromptJob.model_validate(snapshot["job"]),
                                              checkpoint_logical_name=snapshot["checkpoint_logical_name"])
                resources = [RequirementLora.model_validate(item) for item in snapshot["resources"]]
                prepared, target, resolution = self.queue.plan(prepared, run.remote_profile_id,
                                                              run.workflow_profile_id, resources, snapshot["workflow"])
                if (fingerprint(target.remote_profile) != snapshot["remote_fingerprint"]
                        or resolution["bindings"] != snapshot["resolution"]["bindings"]
                        or digest(target.workflow_profile.model_dump(mode="json")) != digest(snapshot["workflow"])):
                    raise ValueError("提交后目标或资源映射变化。")
                if not self.stopping.is_set() and self.queue.deliver_durable(entry, prepared, target):
                    self.store.mark(entry["submission_id"], "enqueued")
            except sqlite3.Error:
                # No executable work was published before persistence. Keep the
                # accepted journal entry so local storage failures can be retried.
                raise
            except Exception:
                self.queue.fail_durable(entry, "submission_dispatch_failed")
                self.store.mark(entry["submission_id"], "failed", "submission_dispatch_failed")

    def _loop(self):
        while not self.stopping.is_set():
            self.wake.wait(1)
            self.wake.clear()
            if not self.stopping.is_set():
                try:
                    self.dispatch_pending()
                except Exception:
                    # A local failure remains durable for recovery; never log secrets.
                    logging.getLogger(__name__).warning("Submission dispatch deferred after a local failure")

    def close(self):
        self.stopping.set()
        self.wake.set()
        if self.worker.is_alive():
            self.worker.join(timeout=5)
