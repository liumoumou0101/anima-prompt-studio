"""Versioned LoRA bindings alongside the existing server workflow mappings."""
from __future__ import annotations

import json
import time

from anima_prompt_studio.domain.execution_models import WorkflowProfile
from ..core.lora_resolution import (
    LoraBinding, MappingConflict, ResourceUnavailable, apply_slot, materialize_lora_stack, resolve_loras, slot_choices,
)
from ..core.requirements import dump
from ..core.workflow_compiler import V3WorkflowCompiler
from ..core.model_versions import model_matches_workflow
from ..remote.comfy_client import ComfyUIClient
from ..storage.runtime_repository import SQLiteRepository
from .packaged_workflows import workflow_revision
from .workflow_catalog import TTL, apply_mapping, catalog, fingerprint, graph_errors
from ..remote.preparation_budget import DirectPreparationTimeout


class LoraCatalog:
    def __init__(self, manager):
        self.manager = manager

    @staticmethod
    def key(remote_id, workflow_id):
        # Unambiguous tuple encoding; workflow ids can themselves contain colons.
        return "workflow_lora_bindings:" + json.dumps([remote_id, workflow_id], separators=(",", ":"))

    def capabilities(self, remote_id, *, credentials=None, refresh=False):
        remote = self.manager.remote(remote_id)
        snapshot = self.manager._read("workflow_capabilities:" + remote_id, {})
        current = (snapshot.get("fingerprint") == fingerprint(remote) and not snapshot.get("error")
                   and 0 <= time.time() - snapshot.get("checked_at", 0) < TTL)
        if not remote.enabled or not remote.connection_ready:
            raise ResourceUnavailable("unknown", "请启用连接并确认 SSH 指纹。")
        if not current and refresh:
            return self._inspect_capabilities(remote_id, credentials)
        if not current:
            raise ResourceUnavailable("unknown", "服务器能力尚未检测或已过期。")
        return remote, snapshot["object_info"]

    def _inspect_capabilities(self, remote_id, credentials):
        try:
            self.manager.inspect(remote_id, credentials)
        except DirectPreparationTimeout:
            raise
        except Exception as exc:
            raise ResourceUnavailable("unknown", "服务器能力检测失败，请检查连接后重试。") from exc
        return self.capabilities(remote_id)

    @staticmethod
    def _workflow_unavailable(*, graph_errors=(), missing_nodes=(), invalid_inputs=()):
        messages = list(graph_errors)
        if missing_nodes:
            experimental = {"AnimaNormalizedAttentionGuidance", "AnimaLayerReplayPatcher"}
            if experimental.intersection(missing_nodes):
                messages.append("缺少实验工作流节点：" + "、".join(missing_nodes) + "；可使用同模型的基础版工作流。")
            else:
                messages.append("缺少工作流节点：" + "、".join(missing_nodes))
        messages.extend(invalid_inputs)
        error = ResourceUnavailable("incompatible_workflow", "；".join(messages))
        error.details.update(graph_errors=list(graph_errors), missing_nodes=list(missing_nodes),
                             invalid_inputs=list(invalid_inputs))
        return error

    def profile(self, workflow_id, *, repository=None):
        profile = next((profile for profile, _ in catalog(self.manager.database, repository=repository) if profile.id == workflow_id), None)
        if profile is None:
            raise KeyError(workflow_id)
        return profile

    def get(self, remote_id, workflow_id):
        profile = self.profile(workflow_id)
        stamp = fingerprint(self.manager.remote(remote_id))
        saved = self.manager._read(self.key(remote_id, workflow_id), {})
        try:
            _, info = self.capabilities(remote_id)
            slots, capabilities_ready = slot_choices(profile, info), True
        except ResourceUnavailable:
            slots, capabilities_ready = {}, False
        return {"mapping_revision": saved.get("mapping_revision", 0),
                "slots": slots, "capabilities_ready": capabilities_ready,
                "workflow_revision": workflow_revision(profile), "remote_fingerprint": stamp,
                "bindings": saved.get("bindings", []),
                "current": not saved or (saved.get("workflow_revision") == workflow_revision(profile)
                                          and saved.get("remote_fingerprint") == stamp)}

    def save(self, remote_id, workflow_id, payload):
        remote, info = self.capabilities(remote_id)
        profile = self.profile(workflow_id)
        if payload.workflow_revision != workflow_revision(profile) or payload.remote_fingerprint != fingerprint(remote):
            raise MappingConflict("连接或工作流版本已变化。")
        choices = slot_choices(profile, info)
        identities, occupied = set(), set()
        for binding in payload.bindings:
            identity = (binding.logical_id, binding.resource_digest)
            if identity in identities or binding.slot_key in occupied or binding.slot_key not in choices or binding.remote_file_name not in choices[binding.slot_key]:
                raise ResourceUnavailable("lora_unmapped", "映射重复或文件不属于该槽位的远端枚举。")
            identities.add(identity)
            occupied.add(binding.slot_key)
        repo = SQLiteRepository(self.manager.database)
        try:
            with repo.connection:
                repo.connection.execute("BEGIN IMMEDIATE")
                key = self.key(remote_id, workflow_id)
                saved = repo.get_setting(key, {})
                if saved.get("mapping_revision", 0) != payload.mapping_revision:
                    raise MappingConflict("LoRA 映射已被更新，请刷新后重试。")
                if fingerprint(repo.get_remote_profile(remote_id)) != payload.remote_fingerprint:
                    raise MappingConflict("连接已被更新，请重新检测。")
                if workflow_revision(self.profile(workflow_id, repository=repo)) != payload.workflow_revision:
                    raise MappingConflict("工作流已被更新，请刷新后重试。")
                value = {**dump(payload), "mapping_revision": payload.mapping_revision + 1}
                repo.connection.execute("INSERT INTO settings(key,value_json) VALUES(?,?) "
                                        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                                        (key, json.dumps(value)))
            return {**value, "current": True}
        finally:
            repo.close()

    def resolve(self, remote_id, workflow_id, model_profile, resources, *, frozen=None, credentials=None, refresh=False):
        if len(resources) > 16:
            raise ResourceUnavailable("incompatible_workflow", "每个任务最多可选择 16 个 LoRA。")
        remote = self.manager.remote(remote_id)
        resources = [item for item in resources if item.enabled]
        directory_mapping_allowed = False
        # Select the execution graph BEFORE checking nodes, assets or slot counts.
        if frozen is not None:
            profile = WorkflowProfile.model_validate(frozen)
            if profile.id != workflow_id:
                raise ResourceUnavailable("incompatible_workflow", "重放工作流 ID 与快照不一致。")
            revision = profile.runtime_assets.get("binding_template_revision", workflow_revision(profile))
        else:
            profile = self.profile(workflow_id)
            revision = workflow_revision(profile)
            saved_mapping = self.manager._read("workflow_mapping:" + remote_id + ":" + workflow_id, {})
            if saved_mapping and (saved_mapping.get("revision") != revision or saved_mapping.get("fingerprint") != fingerprint(remote)):
                raise ResourceUnavailable("incompatible_workflow", "工作流资产映射已过期。")
            directory_mapping_allowed = not saved_mapping and remote.connection_type == "http"
            profile = apply_mapping(profile, saved_mapping.get("mapping", {}))
            profile.runtime_assets["binding_template_revision"] = revision
        if self.manager._read("workflow_disabled:" + workflow_id, False):
            raise ResourceUnavailable("incompatible_workflow", "工作流已停用。")
        if not model_matches_workflow(model_profile, profile):
            raise ResourceUnavailable("incompatible_model", "工作流与当前模型不兼容。")
        # Reusing a historical graph does not authorize replacement files. Trust
        # only assets bound to this model at acceptance, never an unused slot's filename.
        previous = str(profile.runtime_assets.get("accepted_lora_files", "")).split("|") if frozen else []
        accepted = set(previous[1:]) if previous and previous[0] == model_profile else set()
        managed = [item for item in resources if item.sha256]
        unverified = [item for item in managed if item.sha256 not in accepted]
        if unverified:
            from .lora_library import validate_library_resources
            validate_library_resources(self.manager.database, model_profile, unverified)
        errors = graph_errors(profile) + V3WorkflowCompiler().validate_profile(profile)
        if errors:
            raise self._workflow_unavailable(graph_errors=errors)
        saved = self.manager._read(self.key(remote_id, workflow_id), {})
        bindings = [LoraBinding.model_validate(item) for item in saved.get("bindings", [])]
        current = not saved or (saved.get("workflow_revision") == revision and saved.get("remote_fingerprint") == fingerprint(remote))
        inspected = False
        try:
            capability_remote, info = self.capabilities(remote_id)
        except ResourceUnavailable:
            if not refresh:
                raise
            # An expired/missing snapshot already spends this call's inspection.
            inspected = True
            capability_remote, info = self.capabilities(remote_id, credentials=credentials, refresh=True)
        if fingerprint(capability_remote) != fingerprint(remote):
            raise MappingConflict("连接在解析期间变化，请重新提交。")

        def refresh_failed_capabilities():
            nonlocal inspected, info
            if not refresh or inspected:
                return False
            inspected = True
            current_remote, info = self._inspect_capabilities(remote_id, credentials)
            if fingerprint(current_remote) != fingerprint(remote):
                raise MappingConflict("连接在解析期间变化，请重新提交。")
            return True

        while True:
            execution_profile = profile
            if directory_mapping_allowed:
                from .cloud_model_catalog import CloudModelCatalog
                mapping = CloudModelCatalog(self.manager.database).get_submission_mapping(
                    remote_id, model_profile, workflow_id, info)
                if mapping:
                    execution_profile = apply_mapping(profile, mapping)
            execution_profile = materialize_lora_stack(execution_profile, resources)
            ordered = execution_profile.runtime_assets.get("lora_stack") == "ordered/1"
            # A missing loader is a node dependency failure, not proof that the
            # requested LoRA file is absent from an otherwise available loader.
            client = ComfyUIClient("http://unused", session=object())
            client._object_info_cache = info
            missing = client.validate_workflow_nodes(execution_profile.api_workflow)
            if missing:
                if refresh_failed_capabilities():
                    continue
                raise self._workflow_unavailable(missing_nodes=missing,
                    invalid_inputs=client.validate_workflow_inputs(execution_profile.api_workflow))
            try:
                resolved = resolve_loras(resources, execution_profile, info, () if ordered else bindings, mapping_current=current)
            except ResourceUnavailable as exc:
                # Newly installed LoRAs share the same stale enum failure mode.
                if exc.availability == "missing_lora" and refresh_failed_capabilities():
                    continue
                raise
            graph = execution_profile.model_copy(deep=True)
            lookup = {item["slot_key"]: item for item in resolved}
            for slot in graph.lora_slots:
                item = lookup.get(f"{slot.node_id}.{slot.name_input}")
                if item:
                    apply_slot(slot, graph.api_workflow, item["remote_file_name"], item["weight"], item.get("clip_weight"))
                else:
                    apply_slot(slot, graph.api_workflow)
            invalid = client.validate_workflow_inputs(graph.api_workflow)
            if not invalid:
                break
            if not refresh_failed_capabilities():
                raise self._workflow_unavailable(invalid_inputs=invalid)
        if fingerprint(self.manager.remote(remote_id)) != fingerprint(remote):
            raise MappingConflict("连接在解析期间变化，请重新提交。")
        graph.runtime_assets.pop("accepted_lora_files", None)
        if managed:
            graph.runtime_assets["accepted_lora_files"] = "|".join([model_profile, *(item.sha256 for item in managed)])
        return graph, {"availability": "ready", "bindings": resolved, "remote_fingerprint": fingerprint(remote),
                       "workflow_revision": revision, "mapping_revision": saved.get("mapping_revision", 0)}
