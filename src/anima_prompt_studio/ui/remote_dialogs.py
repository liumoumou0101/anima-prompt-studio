from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from anima_prompt_studio.domain.execution_models import (
    HIRES_FIX_WORKFLOW_KIND,
    RemoteAuthType,
    RemoteProfile,
    LoRASlotBinding,
    WorkflowBinding,
    WorkflowProfile,
)
from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.remote.credential_store import CredentialStore, CredentialStoreError
from anima_prompt_studio.services.remote.workflow_compatibility import infer_workflow_model_profiles
from anima_prompt_studio.services.remote.provider_presets import (
    DEFAULT_PROVIDER_PRESET_ID,
    PROVIDER_PRESETS,
    get_provider_preset,
)


WORKFLOW_FIELDS = {
    "positive_prompt": ("正向提示词节点", "text"),
    "negative_prompt": ("负向提示词节点", "text"),
    "checkpoint": ("Checkpoint 节点", "ckpt_name"),
    "text_encoder": ("文本编码器节点", "clip_name"),
    "text_encoder_type": ("文本编码器类型", "type"),
    "vae": ("VAE 节点", "vae_name"),
    "model_shift": ("模型采样 Shift", "shift"),
    "seed": ("采样节点（Seed）", "seed"),
    "steps": ("采样节点（Steps）", "steps"),
    "cfg": ("采样节点（CFG）", "cfg"),
    "sampler": ("采样器节点", "sampler_name"),
    "scheduler": ("调度器节点", "scheduler"),
    "width": ("Latent 节点（宽）", "width"),
    "height": ("Latent 节点（高）", "height"),
    "batch_size": ("Latent 节点（批量）", "batch_size"),
    "filename_prefix": ("保存图片节点", "filename_prefix"),
}

AUTO_REQUIRED_FIELDS = {
    "positive_prompt",
    "negative_prompt",
    "checkpoint",
    "seed",
    "steps",
    "cfg",
    "sampler",
    "scheduler",
    "width",
    "height",
    "batch_size",
    "filename_prefix",
}

HIRES_FIX_BINDING_INPUTS = {
    "refiner_seed": "seed",
    "refiner_steps": "steps",
    "refiner_cfg": "cfg",
    "refiner_sampler": "sampler_name",
    "refiner_scheduler": "scheduler",
    "refiner_denoise": "denoise",
    "upscale_factor": "scale_by",
}


def _linked_node_id(value: Any, workflow: dict[str, Any]) -> str:
    if isinstance(value, (list, tuple)) and value:
        node_id = str(value[0])
        if node_id in workflow:
            return node_id
    return ""


def _find_upstream_node(
    workflow: dict[str, Any],
    start_node_id: str,
    class_name_fragment: str,
) -> str:
    pending = [start_node_id] if start_node_id else []
    visited: set[str] = set()
    while pending:
        node_id = pending.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        node = workflow.get(node_id, {})
        if class_name_fragment.casefold() in str(node.get("class_type", "")).casefold():
            return node_id
        for value in node.get("inputs", {}).values():
            linked = _linked_node_id(value, workflow)
            if linked and linked not in visited:
                pending.append(linked)
    return ""


def _detect_hires_fix_nodes(workflow: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return base sampler, refiner sampler, and latent-upscale node for a two-pass graph."""
    sampler_ids = [
        str(node_id)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and str(node.get("class_type", "")).casefold() == "ksampler"
    ]
    for refiner_id in sampler_ids:
        refiner_inputs = workflow.get(refiner_id, {}).get("inputs", {})
        upscale_id = _linked_node_id(refiner_inputs.get("latent_image"), workflow)
        upscale = workflow.get(upscale_id, {})
        if "latentupscaleby" not in str(upscale.get("class_type", "")).casefold():
            continue
        base_id = _linked_node_id(upscale.get("inputs", {}).get("samples"), workflow)
        if base_id not in sampler_ids or base_id == refiner_id:
            continue
        base_latent_id = _linked_node_id(
            workflow.get(base_id, {}).get("inputs", {}).get("latent_image"),
            workflow,
        )
        if "emptylatentimage" not in str(
            workflow.get(base_latent_id, {}).get("class_type", "")
        ).casefold():
            continue
        return base_id, refiner_id, upscale_id
    return None


def detect_workflow_bindings(workflow: dict[str, Any]) -> dict[str, WorkflowBinding]:
    by_class: dict[str, list[str]] = {}
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        by_class.setdefault(class_type, []).append(str(node_id))

    def first_matching(*class_names: str) -> str:
        for class_name in class_names:
            if by_class.get(class_name):
                return by_class[class_name][0]
        for class_type, node_ids in by_class.items():
            if any(name.casefold() in class_type.casefold() for name in class_names):
                return node_ids[0]
        return ""

    hires_fix_nodes = _detect_hires_fix_nodes(workflow)
    sampler = hires_fix_nodes[0] if hires_fix_nodes else first_matching("KSampler", "KSamplerAdvanced")
    sampler_inputs = workflow.get(sampler, {}).get("inputs", {})
    positive = _linked_node_id(sampler_inputs.get("positive"), workflow)
    negative = _linked_node_id(sampler_inputs.get("negative"), workflow)
    if negative and negative == positive:
        negative = ""
    latent = _linked_node_id(sampler_inputs.get("latent_image"), workflow)
    model_source = _linked_node_id(sampler_inputs.get("model"), workflow)
    checkpoint = _find_upstream_node(workflow, model_source, "CheckpointLoader")
    if not checkpoint:
        checkpoint = _find_upstream_node(workflow, model_source, "UNETLoader")

    clip_nodes = by_class.get("CLIPTextEncode", [])
    for node_id in clip_nodes:
        node = workflow[node_id]
        title = str(node.get("_meta", {}).get("title", "")).casefold()
        text = str(node.get("inputs", {}).get("text", "")).casefold()
        if not positive and ("positive" in title or "正向" in title):
            positive = node_id
        if not negative and ("negative" in title or "负向" in title or "negative" in text):
            negative = node_id
    if not positive and clip_nodes:
        positive = clip_nodes[0]
    if not negative and len(clip_nodes) > 1:
        negative = next((node_id for node_id in clip_nodes if node_id != positive), clip_nodes[1])

    if not latent or "emptylatentimage" not in str(workflow.get(latent, {}).get("class_type", "")).casefold():
        latent = first_matching("EmptyLatentImage")
    if not checkpoint:
        checkpoint = first_matching("CheckpointLoaderSimple", "CheckpointLoader", "UNETLoader")
    save = first_matching("SaveImage")
    text_encoder = first_matching("CLIPLoader")
    vae = first_matching("VAELoader")
    model_sampling = first_matching("ModelSamplingAuraFlow")
    node_map = {
        "positive_prompt": positive,
        "negative_prompt": negative,
        "checkpoint": checkpoint,
        "text_encoder": text_encoder,
        "text_encoder_type": text_encoder,
        "vae": vae,
        "model_shift": model_sampling,
        "seed": sampler,
        "steps": sampler,
        "cfg": sampler,
        "sampler": sampler,
        "scheduler": sampler,
        "width": latent,
        "height": latent,
        "batch_size": latent,
        "filename_prefix": save,
    }
    result: dict[str, WorkflowBinding] = {}
    for field_name, node_id in node_map.items():
        input_name = WORKFLOW_FIELDS[field_name][1]
        if field_name == "checkpoint" and checkpoint:
            checkpoint_inputs = workflow.get(checkpoint, {}).get("inputs", {})
            if "unet_name" in checkpoint_inputs:
                input_name = "unet_name"
        node = workflow.get(node_id, {})
        if node_id and input_name in node.get("inputs", {}):
            result[field_name] = WorkflowBinding(node_id=node_id, input=input_name)
    if hires_fix_nodes:
        _base_sampler, refiner, upscale = hires_fix_nodes
        for field_name, input_name in HIRES_FIX_BINDING_INPUTS.items():
            node_id = upscale if field_name == "upscale_factor" else refiner
            if input_name in workflow.get(node_id, {}).get("inputs", {}):
                result[field_name] = WorkflowBinding(node_id=node_id, input=input_name)
    return result


def classify_workflow(workflow: dict[str, Any], bindings: dict[str, WorkflowBinding]) -> str:
    missing = AUTO_REQUIRED_FIELDS - bindings.keys()
    if missing:
        return "unknown"
    sampler_node = workflow.get(bindings["seed"].node_id, {})
    latent_node = workflow.get(bindings["width"].node_id, {})
    positive_node = workflow.get(bindings["positive_prompt"].node_id, {})
    checkpoint_node = workflow.get(bindings["checkpoint"].node_id, {})
    save_node = workflow.get(bindings["filename_prefix"].node_id, {})
    class_types = [
        str(node.get("class_type", "")).casefold()
        for node in workflow.values()
        if isinstance(node, dict)
    ]
    hires_fix_nodes = _detect_hires_fix_nodes(workflow)
    hires_required = {"refiner_seed", "refiner_denoise", "upscale_factor"}
    if hires_fix_nodes and hires_required <= bindings.keys():
        scale_binding = bindings["upscale_factor"]
        scale_value = workflow.get(scale_binding.node_id, {}).get("inputs", {}).get(scale_binding.input_name)
        hires_allowed_fragments = (
            "ksampler",
            "cliptextencode",
            "emptylatentimage",
            "latentupscaleby",
            "vaedecode",
            "saveimage",
            "checkpointloader",
            "unetloader",
            "cliploader",
            "vaeloader",
            "loraloader",
            "modelsampling",
            "resolutionselector",
        )
        try:
            scale_is_supported = abs(float(scale_value) - 1.5) < 1e-9
        except (TypeError, ValueError):
            scale_is_supported = False
        if (
            scale_is_supported
            and sum(class_type == "ksampler" for class_type in class_types) == 2
            and sum(class_type == "latentupscaleby" for class_type in class_types) == 1
            and sum(class_type == "emptylatentimage" for class_type in class_types) == 1
            and sum(class_type == "saveimage" for class_type in class_types) == 1
            and all(any(fragment in class_type for fragment in hires_allowed_fragments) for class_type in class_types)
        ):
            return HIRES_FIX_WORKFLOW_KIND
    basic_allowed_fragments = (
        "ksampler",
        "cliptextencode",
        "emptylatentimage",
        "vaedecode",
        "saveimage",
        "checkpointloader",
        "unetloader",
        "cliploader",
        "vaeloader",
        "loraloader",
        "modelsampling",
        "resolutionselector",
        "animalayerreplaypatcher",
        "animanormalizedattentionguidance",
    )
    simple_graph = (
        sum(class_type == "ksampler" for class_type in class_types) == 1
        and sum(class_type == "saveimage" for class_type in class_types) == 1
        and sum(class_type == "emptylatentimage" for class_type in class_types) == 1
        and all(any(fragment in class_type for fragment in basic_allowed_fragments) for class_type in class_types)
    )
    if (
        simple_graph
        and
        str(sampler_node.get("class_type", "")) == "KSampler"
        and "emptylatentimage" in str(latent_node.get("class_type", "")).casefold()
        and "cliptextencode" in str(positive_node.get("class_type", "")).casefold()
        and any(
            name in str(checkpoint_node.get("class_type", "")).casefold()
            for name in ("checkpointloader", "unetloader")
        )
        and "saveimage" in str(save_node.get("class_type", "")).casefold()
    ):
        return "txt2img_basic"
    return "unknown"


def build_auto_workflow_profile(
    workflow: dict[str, Any],
    source_path: Path,
    compatible_model_profile: str = "",
) -> tuple[WorkflowProfile, list[str]]:
    profile_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", source_path.stem).strip("_") or "comfy_workflow"
    bindings = detect_workflow_bindings(workflow)
    missing = sorted(AUTO_REQUIRED_FIELDS - bindings.keys())
    profile = WorkflowProfile(
        id=profile_id,
        display_name=source_path.stem,
        api_workflow=workflow,
        bindings=bindings,
        workflow_kind=classify_workflow(workflow, bindings),
        lora_slots=detect_lora_slots(workflow),
        compatible_model_profiles=(
            [compatible_model_profile]
            if compatible_model_profile
            else infer_workflow_model_profiles(workflow, source_path.name)
        ),
        runtime_assets=detect_runtime_assets(workflow, bindings),
        source_path=str(source_path),
        notes="由软件根据 ComfyUI API 工作流连线自动识别。",
    )
    return profile, missing


def detect_runtime_assets(
    workflow: dict[str, Any],
    bindings: dict[str, WorkflowBinding],
) -> dict[str, str | float]:
    """Snapshot loader inputs that must stay coupled to this workflow."""
    assets: dict[str, str | float] = {}
    for field_name in ("checkpoint", "text_encoder", "text_encoder_type", "vae", "model_shift"):
        binding = bindings.get(field_name)
        if binding is None:
            continue
        value = workflow.get(binding.node_id, {}).get("inputs", {}).get(binding.input_name)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            assets[field_name] = float(value) if field_name == "model_shift" else str(value)
    return assets


def detect_lora_slots(workflow: dict[str, Any]) -> list[LoRASlotBinding]:
    slots: list[LoRASlotBinding] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "loraloader" not in str(node.get("class_type", "")).casefold():
            continue
        inputs = node.get("inputs", {})
        required = {"lora_name", "strength_model", "strength_clip"}
        if required <= set(inputs):
            slots.append(LoRASlotBinding(node_id=str(node_id)))
    return slots


class RemoteProfileDialog(QDialog):
    def __init__(self, profile: RemoteProfile | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("云主机配置")
        self.resize(620, 560)
        self._id = profile.id if profile else ""
        self._startup_mode = profile.startup_mode if profile else "manual"
        self._startup_command = profile.startup_command if profile else ""
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.provider_preset = QComboBox()
        for preset in PROVIDER_PRESETS:
            self.provider_preset.addItem(preset.display_name, preset.id)
        preset_id = profile.provider_preset_id if profile else DEFAULT_PROVIDER_PRESET_ID
        self.provider_preset.setCurrentIndex(max(0, self.provider_preset.findData(preset_id)))
        self.display_name = QLineEdit(profile.display_name if profile else "云端 ComfyUI")
        self.ssh_host = QLineEdit(profile.ssh_host if profile else "")
        default_preset = get_provider_preset(preset_id)
        self.ssh_port = QSpinBox(); self.ssh_port.setRange(1, 65535); self.ssh_port.setValue(profile.ssh_port if profile else default_preset.ssh_port)
        self.ssh_user = QLineEdit(profile.ssh_user if profile else default_preset.ssh_user)
        self.auth_type = QComboBox()
        self.auth_type.addItem("SSH 私钥", RemoteAuthType.PRIVATE_KEY.value)
        self.auth_type.addItem("密码", RemoteAuthType.PASSWORD.value)
        self.auth_type.addItem("SSH Agent / 系统密钥", RemoteAuthType.AGENT.value)
        if profile:
            self.auth_type.setCurrentIndex(max(0, self.auth_type.findData(profile.auth_type.value)))
        else:
            self.auth_type.setCurrentIndex(max(0, self.auth_type.findData(default_preset.auth_type.value)))
        self.private_key_path = QLineEdit(profile.private_key_path if profile else "")
        key_row = QWidget(); key_layout = QHBoxLayout(key_row); key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(self.private_key_path)
        browse = QPushButton("选择…"); browse.clicked.connect(self._choose_key); key_layout.addWidget(browse)
        self.fingerprint = QLineEdit(profile.known_host_fingerprint if profile else "")
        self.fingerprint.setPlaceholderText("首次连接测试时确认并自动保存")
        self.comfy_host = QLineEdit(profile.comfy_host if profile else default_preset.comfy_host)
        self.comfy_port = QSpinBox(); self.comfy_port.setRange(1, 65535); self.comfy_port.setValue(profile.comfy_port if profile else default_preset.comfy_port)
        self.model_aliases = QTextEdit()
        self.model_aliases.setMaximumHeight(100)
        self.model_aliases.setPlaceholderText('{"anima_turbo_v1": "实际模型文件.safetensors"}')
        self.model_aliases.setPlainText(json.dumps(profile.model_aliases if profile else {}, ensure_ascii=False, indent=2))
        self.enabled = QCheckBox("启用此配置"); self.enabled.setChecked(profile.enabled if profile else True)
        form.addRow("云平台预设", self.provider_preset)
        form.addRow("名称", self.display_name)
        form.addRow("SSH 地址", self.ssh_host)
        form.addRow("SSH 端口", self.ssh_port)
        form.addRow("SSH 用户", self.ssh_user)
        form.addRow("认证方式", self.auth_type)
        form.addRow("私钥文件", key_row)
        form.addRow("主机指纹", self.fingerprint)
        form.addRow("云端 ComfyUI 地址", self.comfy_host)
        form.addRow("云端 ComfyUI 端口", self.comfy_port)
        form.addRow("模型文件映射（JSON）", self.model_aliases)
        form.addRow("", self.enabled)
        self.provider_preset.currentIndexChanged.connect(self._apply_provider_preset)
        layout.addLayout(form)
        hint = QLabel("密码和私钥口令不会保存；连接时按需输入。ComfyUI 地址通常保持 127.0.0.1。")
        hint.setWordWrap(True); hint.setStyleSheet("color: #777"); layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 SSH 私钥")
        if path:
            self.private_key_path.setText(path)

    def _apply_provider_preset(self) -> None:
        preset = get_provider_preset(self.provider_preset.currentData() or DEFAULT_PROVIDER_PRESET_ID)
        self.ssh_port.setValue(preset.ssh_port)
        self.ssh_user.setText(preset.ssh_user)
        self.auth_type.setCurrentIndex(max(0, self.auth_type.findData(preset.auth_type.value)))
        self.comfy_host.setText(preset.comfy_host)
        self.comfy_port.setValue(preset.comfy_port)
        if preset.auth_type != RemoteAuthType.PRIVATE_KEY:
            self.private_key_path.clear()

    def _validate_and_accept(self) -> None:
        try:
            self.result_profile()
        except Exception as exc:
            QMessageBox.warning(self, "配置无效", str(exc))
            return
        self.accept()

    def result_profile(self) -> RemoteProfile:
        if not self.ssh_host.text().strip():
            raise ValueError("SSH 地址不能为空。")
        if not self.ssh_user.text().strip():
            raise ValueError("SSH 用户不能为空。")
        aliases = json.loads(self.model_aliases.toPlainText().strip() or "{}")
        if not isinstance(aliases, dict):
            raise ValueError("模型文件映射必须是 JSON 对象。")
        values = dict(
            provider_preset_id=self.provider_preset.currentData() or DEFAULT_PROVIDER_PRESET_ID,
            display_name=self.display_name.text().strip() or "云端 ComfyUI",
            ssh_host=self.ssh_host.text().strip(),
            ssh_port=self.ssh_port.value(),
            ssh_user=self.ssh_user.text().strip(),
            auth_type=RemoteAuthType(self.auth_type.currentData()),
            private_key_path=self.private_key_path.text().strip(),
            known_host_fingerprint=self.fingerprint.text().strip(),
            comfy_host=self.comfy_host.text().strip() or "127.0.0.1",
            comfy_port=self.comfy_port.value(),
            model_aliases={str(key): str(value) for key, value in aliases.items()},
            startup_mode=self._startup_mode,
            startup_command=self._startup_command,
            enabled=self.enabled.isChecked(),
        )
        if self._id:
            values["id"] = self._id
        return RemoteProfile(**values)


class RemoteProfileManagerDialog(QDialog):
    """Manage reusable SSH targets independently from the generation form."""

    def __init__(
        self,
        repository: SQLiteRepository,
        credential_store: CredentialStore,
        selected_profile_id: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.credential_store = credential_store
        self.selected_profile_id = selected_profile_id
        self.setWindowTitle("管理云主机连接")
        self.resize(860, 460)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "每个云显卡镜像可以保存为一个连接。复制连接会保留 ComfyUI 和模型映射，"
            "但会清除 SSH 主机指纹且不会复制密码。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("background: #eef4ff; color: #234a83; padding: 8px; border-radius: 5px")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["状态", "连接名称", "云平台", "SSH 地址", "用户", "ComfyUI"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self.edit_selected)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        for label, slot in (
            ("新增", self.add_profile),
            ("编辑", self.edit_selected),
            ("复制为新镜像", self.duplicate_selected),
            ("启用 / 停用", self.toggle_selected),
            ("删除", self.delete_selected),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch()
        use_button = QPushButton("使用选中连接")
        use_button.setProperty("buttonRole", "primary")
        use_button.clicked.connect(self.use_selected)
        actions.addWidget(use_button)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self.refresh_profiles(selected_profile_id)

    def refresh_profiles(self, selected_profile_id: str = "") -> None:
        wanted = selected_profile_id or self.selected_profile_id
        profiles = self.repository.list_remote_profiles()
        self.table.setRowCount(len(profiles))
        selected_row = -1
        for row, profile in enumerate(profiles):
            values = (
                "启用" if profile.enabled else "停用",
                profile.display_name,
                get_provider_preset(profile.provider_preset_id).display_name,
                f"{profile.ssh_host}:{profile.ssh_port}",
                profile.ssh_user,
                f"{profile.comfy_host}:{profile.comfy_port}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, profile.id)
                if not profile.enabled:
                    item.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(row, column, item)
            if profile.id == wanted:
                selected_row = row
        if selected_row < 0 and profiles:
            selected_row = 0
        if selected_row >= 0:
            self.table.selectRow(selected_row)
            self.selected_profile_id = str(self.table.item(selected_row, 0).data(Qt.UserRole))
        else:
            self.selected_profile_id = ""

    def _selection_changed(self) -> None:
        profile_id = self._selected_profile_id()
        if profile_id:
            self.selected_profile_id = profile_id

    def _selected_profile_id(self) -> str:
        row = self.table.currentRow()
        if row < 0 or not self.table.item(row, 0):
            return ""
        return str(self.table.item(row, 0).data(Qt.UserRole) or "")

    def _selected_profile(self) -> RemoteProfile | None:
        profile_id = self._selected_profile_id()
        return self.repository.get_remote_profile(profile_id) if profile_id else None

    def add_profile(self) -> None:
        dialog = RemoteProfileDialog(parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        profile = dialog.result_profile()
        self.repository.save_remote_profile(profile)
        self.refresh_profiles(profile.id)

    def edit_selected(self) -> None:
        profile = self._selected_profile()
        if not profile:
            return
        dialog = RemoteProfileDialog(profile, self)
        if dialog.exec() != QDialog.Accepted:
            return
        updated = dialog.result_profile()
        self.repository.save_remote_profile(updated)
        self.refresh_profiles(updated.id)

    def duplicate_selected(self) -> None:
        profile = self._selected_profile()
        if not profile:
            return
        duplicate = profile.model_copy(
            update={
                "id": str(uuid4()),
                "display_name": f"{profile.display_name}（新镜像）",
                "known_host_fingerprint": "",
                "enabled": True,
            },
            deep=True,
        )
        self.repository.save_remote_profile(duplicate)
        self.repository.set_setting(f"remember_remote_password:{duplicate.id}", False)
        self.refresh_profiles(duplicate.id)

    def toggle_selected(self) -> None:
        profile = self._selected_profile()
        if not profile:
            return
        updated = profile.model_copy(update={"enabled": not profile.enabled})
        self.repository.save_remote_profile(updated)
        self.refresh_profiles(updated.id)

    def delete_selected(self, *, confirm: bool = True) -> None:
        profile = self._selected_profile()
        if not profile:
            return
        if confirm and QMessageBox.question(
            self,
            "删除云主机连接",
            f"确定删除“{profile.display_name}”吗？生成历史不会被删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self.repository.delete_remote_profile(profile.id)
        self.repository.delete_setting(f"remember_remote_password:{profile.id}")
        if self.repository.get_setting("last_remote_profile_id", "") == profile.id:
            self.repository.set_setting("last_remote_profile_id", "")
        try:
            self.credential_store.delete_password(profile.id)
        except CredentialStoreError as exc:
            QMessageBox.warning(self, "凭据清理失败", str(exc))
        self.selected_profile_id = ""
        self.refresh_profiles()

    def use_selected(self) -> None:
        profile = self._selected_profile()
        if not profile:
            return
        if not profile.enabled:
            profile = profile.model_copy(update={"enabled": True})
            self.repository.save_remote_profile(profile)
        self.selected_profile_id = profile.id
        self.accept()


class WorkflowProfileDialog(QDialog):
    def __init__(self, workflow: dict[str, Any], source_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("导入 ComfyUI API 工作流")
        self.resize(620, 680)
        self.workflow = workflow
        self.source_path = source_path
        detected = detect_workflow_bindings(workflow)
        self.detected_lora_slots = detect_lora_slots(workflow)
        self.detected_kind = classify_workflow(workflow, detected)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        default_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", source_path.stem).strip("_") or "comfy_workflow"
        self.profile_id = QLineEdit(default_id)
        self.display_name = QLineEdit(source_path.stem)
        self.compatible_models = QLineEdit()
        self.compatible_models.setPlaceholderText("例如：anima_turbo_v1；留空表示不限")
        form.addRow("工作流 ID", self.profile_id)
        form.addRow("显示名称", self.display_name)
        form.addRow("兼容模型配置", self.compatible_models)
        self.node_fields: dict[str, QLineEdit] = {}
        for field_name, (label, _) in WORKFLOW_FIELDS.items():
            edit = QLineEdit(detected[field_name].node_id if field_name in detected else "")
            self.node_fields[field_name] = edit
            form.addRow(label, edit)
        layout.addLayout(form)
        hint = QLabel(
            "自动识别不完整时才需要人工校准。请重点确认正向/负向节点；V2 当前只保证基础文生图的标准 "
            "KSampler、EmptyLatentImage、Checkpoint Loader 和 SaveImage 输入名称。"
            f"工作流类型：{self.detected_kind}；检测到 {len(self.detected_lora_slots)} 个固定 LoRA 插槽。"
        )
        hint.setWordWrap(True); hint.setStyleSheet("color: #777"); layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        try:
            self.result_profile()
        except Exception as exc:
            QMessageBox.warning(self, "工作流无效", str(exc))
            return
        self.accept()

    def result_profile(self) -> WorkflowProfile:
        if not self.profile_id.text().strip():
            raise ValueError("工作流 ID 不能为空。")
        bindings: dict[str, WorkflowBinding] = {}
        for field_name, edit in self.node_fields.items():
            node_id = edit.text().strip()
            if not node_id:
                if field_name == "negative_prompt":
                    continue
                raise ValueError(f"缺少{WORKFLOW_FIELDS[field_name][0]}。")
            input_name = WORKFLOW_FIELDS[field_name][1]
            node = self.workflow.get(node_id)
            if not isinstance(node, dict):
                raise ValueError(f"节点不存在：{node_id}")
            if input_name not in node.get("inputs", {}):
                raise ValueError(f"节点 {node_id} 没有输入 {input_name}。")
            bindings[field_name] = WorkflowBinding(node_id=node_id, input=input_name)
        compatible = [item.strip() for item in self.compatible_models.text().split(",") if item.strip()]
        return WorkflowProfile(
            id=self.profile_id.text().strip(),
            display_name=self.display_name.text().strip() or self.profile_id.text().strip(),
            api_workflow=self.workflow,
            bindings=bindings,
            workflow_kind=classify_workflow(self.workflow, bindings),
            lora_slots=self.detected_lora_slots,
            compatible_model_profiles=compatible,
            source_path=str(self.source_path),
        )
