"""Official resources, user copies and server bindings have separate ownership."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from threading import Event, Lock, Thread
from uuid import uuid4

from anima_prompt_studio.domain.execution_models import WorkflowProfile, RemoteCredentials, RemoteAuthType
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from anima_prompt_studio_v3.remote.comfy_client import ComfyUIClient
from anima_prompt_studio_v3.remote.credential_store import CredentialStore
from anima_prompt_studio_v3.remote.ssh_tunnel import SshTunnel
from ..core.workflow_compiler import V3WorkflowCompiler as WorkflowRenderer
from .packaged_workflows import packaged_workflow_profiles, workflow_revision, workflow_catalog_manifest

ASSET_INPUTS = {"unet_name", "ckpt_name", "clip_name", "clip_name1", "clip_name2", "vae_name", "lora_name"}
TTL = 900


def graph_errors(profile):
    graph = profile.api_workflow
    errors = []
    edges = {}
    if not graph or len(graph) > 2000:
        return ["工作流须包含 1–2000 个节点。"]
    for key, node in graph.items():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            errors.append(f"节点 {key} 格式无效。")
            continue
        edges[key] = []
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                if value[0] not in graph or value[1] < 0:
                    errors.append(f"节点 {key} 引用了不存在的节点或输出。")
                edges[key].append(value[0])
    # Iterative topological check avoids recursion limits on imported graphs.
    pending = {key: set(value) for key, value in edges.items()}
    while pending:
        roots = {key for key, value in pending.items() if not value}
        if not roots:
            errors.append("工作流连接存在环或无效依赖。")
            break
        pending = {key: value - roots for key, value in pending.items() if key not in roots}
    return errors


def fingerprint(profile):
    values = profile.model_dump(mode="json")
    values.pop("display_name", None)
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def catalog(database, *, repository=None):
    official = {p.id: p for p in packaged_workflow_profiles()}
    repo = repository if repository is not None else SQLiteRepository(database)
    try:
        result = []
        for p in repo.list_workflow_profiles():
            revision = workflow_revision(p)
            old = repo.get_setting("workflow_template_revision:" + p.id)
            if p.id in official and (revision == workflow_revision(official[p.id]) or revision == old):
                continue
            result.append((p, "user"))
        user_ids = {p.id for p, _ in result}
        for p in official.values():
            # Official dimensions are runtime bindings, not a dependency on a
            # third-party UI resolution picker left over from the author's graph.
            p = p.model_copy(deep=True)
            dimension_nodes = set()
            for name, default in (("width", 896), ("height", 1152)):
                binding = p.bindings[name]
                inputs = p.api_workflow[binding.node_id]["inputs"]
                value = inputs[binding.input_name]
                if isinstance(value, list):
                    dimension_nodes.add(value[0])
                inputs[binding.input_name] = default
            for node_id in dimension_nodes:
                referenced = any(isinstance(value, list) and value and value[0] == node_id
                                 for node in p.api_workflow.values() for value in node.get("inputs", {}).values())
                if not referenced and p.api_workflow.get(node_id, {}).get("class_type") == "ResolutionSelector":
                    del p.api_workflow[node_id]
            if p.id in user_ids:
                p = p.model_copy(update={"id": "official:" + p.id})
            result.append((p, "official"))
        return sorted(result, key=lambda pair: (is_experimental(pair[0]), pair[1] != "official", pair[0].display_name))
    finally:
        if repository is None:
            repo.close()


def is_experimental(profile):
    declaration = workflow_catalog_manifest()["templates"].get(profile.id.removeprefix("official:"))
    if declaration and declaration["tier"] == "experimental":
        return True
    return any(n.get("class_type") in {"AnimaLayerReplayPatcher", "AnimaNormalizedAttentionGuidance"}
               for n in profile.api_workflow.values() if isinstance(n, dict))


def apply_mapping(profile, mapping):
    result = profile.model_copy(deep=True)
    for key, value in mapping.items():
        node_id, input_name = key.rsplit(".", 1)
        node = result.api_workflow.get(node_id, {})
        if input_name not in ASSET_INPUTS or input_name not in node.get("inputs", {}):
            raise ValueError("映射只能修改已声明的模型资产输入。")
        node["inputs"][input_name] = value
        for field, binding in result.bindings.items():
            if binding.node_id == node_id and binding.input_name == input_name:
                result.runtime_assets[field] = value
    # Renderer must not replace an explicitly bound checkpoint with an old alias.
    result.runtime_assets["server_binding"] = "v1"
    return result


class WorkflowCatalog:
    def __init__(self, database):
        self.database = Path(database).resolve()
        self._submission_inspection_lock = Lock()

    def archive_official_versions(self):
        repo = SQLiteRepository(self.database)
        try:
            with repo.connection:
                for profile, origin in catalog(self.database):
                    if origin == "official":
                        repo.connection.execute("INSERT OR IGNORE INTO settings(key,value_json) VALUES(?,?)",
                            ("workflow_version:" + profile.id + ":" + workflow_revision(profile), profile.model_dump_json()))
        finally:
            repo.close()

    def versions(self, workflow_id):
        prefix = "workflow_version:" + workflow_id + ":"
        repo = SQLiteRepository(self.database)
        try:
            return [{"revision": row[0][len(prefix):], "display_name": json.loads(row[1])["display_name"]}
                    for row in repo.connection.execute("SELECT key,value_json FROM settings WHERE substr(key,1,?)=? ORDER BY key", (len(prefix), prefix))]
        finally:
            repo.close()

    def restore_version(self, workflow_id, revision):
        payload = self._read("workflow_version:" + workflow_id + ":" + revision)
        if not payload:
            raise KeyError(revision)
        return self.import_profile(payload)

    def _read(self, key, default=None):
        repo = SQLiteRepository(self.database)
        try:
            return repo.get_setting(key, default)
        finally:
            repo.close()

    def _write(self, key, value):
        repo = SQLiteRepository(self.database)
        try:
            repo.set_setting(key, value)
        finally:
            repo.close()

    def remote(self, remote_id):
        repo = SQLiteRepository(self.database)
        try:
            return repo.get_remote_profile(remote_id)
        finally:
            repo.close()

    def invalidate(self, remote_id):
        key = "workflow_capabilities:" + remote_id
        snapshot = self._read(key)
        if snapshot:
            self._write(key, {**snapshot, "checked_at": 0})

    def inspect(self, remote_id, credentials=None, cancel=None):
        profile = self.remote(remote_id)
        if not profile.enabled or not profile.known_host_fingerprint:
            raise ValueError("请启用连接并确认 SSH 主机指纹。")
        credentials = credentials or RemoteCredentials()
        if profile.auth_type == RemoteAuthType.PASSWORD and not credentials.password:
            credentials = credentials.model_copy(update={"password": CredentialStore().read_password(profile.id)})
        tunnel = SshTunnel(profile, connect_timeout=10)
        stamp = fingerprint(profile)
        try:
            tunnel.open(credentials)
            client = ComfyUIClient(tunnel.base_url, timeout=(10, 30))
            environment = client.validate_environment()
            info = client.object_info(refresh=True)
            if cancel and cancel.is_set():
                return
            if fingerprint(self.remote(remote_id)) != stamp:
                raise ValueError("连接配置已更改，请重新检测。")
            # Persist capability data, not SSH credentials or raw system arguments.
            self._write("workflow_capabilities:" + remote_id, {
                "fingerprint": stamp, "checked_at": time.time(), "object_info": info,
                "devices": environment.devices, "error": None,
            })
        except Exception:
            if not cancel or not cancel.is_set():
                self._write("workflow_capabilities:" + remote_id, {
                    **self._read("workflow_capabilities:" + remote_id, {}),
                    "fingerprint": stamp, "checked_at": time.time(), "error": "连接或能力检测失败，请检查连接后重试。",
                })
            raise
        finally:
            tunnel.close()

    def report(self, remote_id):
        remote = self.remote(remote_id)
        snapshot = self._read("workflow_capabilities:" + remote_id, {})
        state = "unchecked"
        if snapshot:
            state = "connection_failed" if snapshot.get("error") else "ready"
            if snapshot.get("fingerprint") != fingerprint(remote) or time.time() - snapshot.get("checked_at", 0) > TTL:
                state = "stale"
        if not remote.enabled or not remote.known_host_fingerprint:
            state = "unchecked"
        info = snapshot.get("object_info", {})
        items = []
        for profile, origin in catalog(self.database):
            revision = workflow_revision(profile)
            saved = self._read("workflow_mapping:" + remote_id + ":" + profile.id, {})
            mapping_current = saved.get("revision") == revision and saved.get("fingerprint") == fingerprint(remote)
            mapping = saved.get("mapping", {}) if mapping_current else {}
            resolved = apply_mapping(profile, mapping)
            assets = []
            for node_id, node in resolved.api_workflow.items():
                if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                    continue
                definition = info.get(node.get("class_type"), {})
                groups = definition.get("input", {})
                specs = {**groups.get("required", {}), **groups.get("optional", {})}
                for name, value in node.get("inputs", {}).items():
                    if name not in ASSET_INPUTS or not isinstance(value, str):
                        continue
                    spec = specs.get(name, [])
                    choices = spec[0] if spec and isinstance(spec[0], list) else []
                    assets.append({"key": f"{node_id}.{name}", "value": value, "choices": choices,
                                   "mapped": f"{node_id}.{name}" in mapping})
            errors = graph_errors(resolved)
            if not errors:
                errors = WorkflowRenderer().validate_profile(resolved)
            if not resolved.compatible_model_profiles or resolved.workflow_kind == "unknown":
                errors.append("该工作流尚未声明受支持的生成类型及兼容模型。")
            missing = []
            invalid = []
            if state == "ready" and not errors:
                client = ComfyUIClient("http://unused", session=object())
                client._object_info_cache = info
                missing = client.validate_workflow_nodes(resolved.api_workflow)
                invalid = client.validate_workflow_inputs(resolved.api_workflow)
                errors += ["缺少节点：" + name for name in missing] + invalid
            item_state = state
            if state == "ready" and errors:
                item_state = "missing_nodes" if missing else "invalid_inputs"
            if state != "ready":
                errors.append({"unchecked": "请先检测模型与工作流", "stale": "检测已过期或连接配置变化，请重新检测", "connection_failed": "连接检测失败，请重试"}.get(state, state))
            if self._read("workflow_disabled:" + profile.id, False):
                item_state = "disabled"
                errors.append("该工作流已停用。")
            elif saved and not mapping_current and state == "ready":
                item_state = "mapping_stale"
                errors.append("模板或连接已变化，请重新确认文件映射；不会自动退回默认文件。")
            items.append({"workflow_id": profile.id, "display_name": profile.display_name,
                          "revision": revision, "origin": origin, "experimental": is_experimental(profile),
                          "model_profiles": profile.compatible_model_profiles, "workflow_kind": profile.workflow_kind,
                          "state": item_state, "errors": errors, "assets": assets,
                          "template_version": workflow_catalog_manifest()["templates"].get(profile.id.removeprefix("official:"), {}).get("version") if origin == "official" else None})
        return {"remote_profile_id": remote_id, "checked_at": snapshot.get("checked_at"),
                "devices": snapshot.get("devices", []), "items": items, "generation_verified": False}

    def save_mapping(self, remote_id, workflow_id, revision, mapping):
        report = self.report(remote_id)
        item = next((i for i in report["items"] if i["workflow_id"] == workflow_id), None)
        if not item or item["revision"] != revision:
            raise ValueError("模板已改变，请刷新后重新配置。")
        if item["state"] in {"unchecked", "stale", "connection_failed"}:
            raise ValueError("请先重新检测服务器。")
        allowed = {a["key"]: a["choices"] for a in item["assets"]}
        if any(k not in allowed or v not in allowed[k] for k, v in mapping.items()):
            raise ValueError("所选资产不在该服务器的可选文件中。")
        self._write("workflow_mapping:" + remote_id + ":" + workflow_id, {
            "revision": revision, "fingerprint": fingerprint(self.remote(remote_id)), "mapping": mapping,
        })
        return self.report(remote_id)

    def resolve_for_submission(self, remote_id, workflow_id, credentials):
        """Refresh expired capabilities once, without replacing the selected graph."""
        if not self._submission_inspection_lock.acquire(timeout=45):
            raise ValueError("服务器依赖检测仍在进行，请稍后重试。")
        try:
            item = next((i for i in self.report(remote_id)["items"] if i["workflow_id"] == workflow_id), None)
            if item and item["state"] in {"unchecked", "stale", "connection_failed"}:
                remote = self.remote(remote_id)
                if not remote.enabled or not remote.known_host_fingerprint:
                    raise ValueError("请启用连接并确认 SSH 主机指纹后再生成。")
                try:
                    self.inspect(remote_id, credentials)
                except Exception as exc:
                    raise ValueError("提交前自动检测失败，任务尚未入队。请检查 SSH 认证和 ComfyUI 服务后重试。") from exc
            return self.resolve(remote_id, workflow_id)
        finally:
            self._submission_inspection_lock.release()

    def resolve(self, remote_id, workflow_id):
        item = next((i for i in self.report(remote_id)["items"] if i["workflow_id"] == workflow_id), None)
        if not item:
            raise ValueError("工作流不存在，请重新选择。")
        if item["state"] != "ready":
            raise ValueError("；".join(item["errors"]) or "工作流未就绪")
        profile = next(p for p, _ in catalog(self.database) if p.id == workflow_id)
        if workflow_revision(profile) != item["revision"]:
            raise ValueError("工作流在解析期间已变化，请刷新后重新提交。")
        mapping = {a["key"]: a["value"] for a in item["assets"]}
        return apply_mapping(profile, mapping)

    def set_enabled(self, workflow_id, enabled):
        if not any(p.id == workflow_id for p, _ in catalog(self.database)):
            raise KeyError(workflow_id)
        self._write("workflow_disabled:" + workflow_id, not enabled)
        return {"enabled": enabled}

    def import_profile(self, payload):
        encoded = json.dumps(payload, ensure_ascii=False)
        if len(encoded.encode()) > 2_000_000:
            raise ValueError("工作流文件不能超过 2 MB。")
        if payload.get("schema") == "anima-user-workflow/1":
            payload = payload.get("profile")
            if not isinstance(payload, dict):
                raise ValueError("导出文件缺少有效的 profile 对象。")
        if "api_workflow" not in payload:
            from .workflow_import import profile_from_api
            payload = profile_from_api(payload).model_dump(mode="json")
        profile = WorkflowProfile.model_validate(payload)
        errors = graph_errors(profile)
        if not errors:
            errors = WorkflowRenderer().validate_profile(profile)
        if errors or not profile.compatible_model_profiles or profile.workflow_kind == "unknown":
            raise ValueError("；".join(errors) or "必须声明兼容模型。")
        source = {"id": profile.id, "revision": workflow_revision(profile)}
        profile = profile.model_copy(update={"id": "user:" + str(uuid4()), "source_path": "user-import"})
        repo = SQLiteRepository(self.database)
        try:
            repo.save_workflow_profile(profile)
            repo.set_setting("workflow_source:" + profile.id, source)
        finally:
            repo.close()
        return {"id": profile.id, "display_name": profile.display_name}

    def export_profile(self, workflow_id):
        profile = next((p for p, _ in catalog(self.database) if p.id == workflow_id), None)
        if not profile:
            raise KeyError(workflow_id)
        result = profile.model_dump(mode="json")
        result["source_path"] = ""
        # Export may contain user-supplied node inputs. UI requires review before sharing.
        return {"schema": "anima-user-workflow/1", "profile": result}

    def read_remote_file(self, remote_id, path, credentials):
        if not path.startswith("/") or not path.lower().endswith(".json") or len(path) > 2048:
            raise ValueError("请输入云端 JSON 文件的绝对路径。")
        profile = self.remote(remote_id)
        if not profile.enabled or not profile.known_host_fingerprint:
            raise ValueError("请先启用连接并确认 SSH 指纹。")
        if profile.auth_type == RemoteAuthType.PASSWORD and not credentials.password:
            credentials = credentials.model_copy(update={"password": CredentialStore().read_password(remote_id)})
        tunnel = SshTunnel(profile, connect_timeout=10)
        try:
            tunnel.open(credentials)
            with tunnel.client.open_sftp() as sftp:
                sftp.get_channel().settimeout(30)
                if sftp.stat(path).st_size > 2_000_000:
                    raise ValueError("文件不能超过 2 MB。")
                with sftp.open(path, "rb") as stream:
                    content = stream.read(2_000_001)
                if len(content) > 2_000_000:
                    raise ValueError("文件不能超过 2 MB。")
                payload = json.loads(content.decode("utf-8-sig"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON 须为工作流对象。")
                return {"document": payload}
        finally:
            tunnel.close()


class InspectionJobs:
    """Per-runtime bounded checks; cancellation prevents publishing stale results."""
    def __init__(self, manager):
        self.manager = manager
        self.lock = Lock()
        self.jobs = {}

    def start(self, remote_id, credentials):
        with self.lock:
            current = self.jobs.get(remote_id)
            if current and current["state"] == "running":
                return {"state": "running"}
            if sum(j["state"] == "running" for j in self.jobs.values()) >= 2:
                raise ValueError("已有两个检测任务，请稍后重试。")
            job = {"state": "running", "cancel": Event(), "error": None}
            self.jobs[remote_id] = job
        def run():
            try:
                self.manager.inspect(remote_id, credentials, job["cancel"])
                job["state"] = "canceled" if job["cancel"].is_set() else "completed"
            except Exception:
                job["state"] = "canceled" if job["cancel"].is_set() else "failed"
                job["error"] = "检测失败，请确认凭据、SSH 指纹和 ComfyUI 服务后重试。"
        Thread(target=run, daemon=True, name="workflow-inspection").start()
        return {"state": "running"}

    def status(self, remote_id):
        with self.lock:
            job = self.jobs.get(remote_id, {"state": "idle", "error": None})
            return {"state": job["state"], "error": job["error"]}

    def cancel(self, remote_id):
        with self.lock:
            if remote_id in self.jobs:
                self.jobs[remote_id]["cancel"].set()
        return self.status(remote_id)

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job["cancel"].set()
