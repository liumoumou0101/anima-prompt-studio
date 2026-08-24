from __future__ import annotations

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from anima_prompt_studio.services.ai_prompt_service import (
    AIAPIStyle,
    AIClient,
    AIEngineConfig,
    OPENCODE_GO_BASE_URL,
    OPENCODE_GO_KNOWN_MODELS,
    opencode_go_model_label,
)
from anima_prompt_studio.ui.ai_workers import AIModelListWorker


class AIEngineDialog(QDialog):
    def __init__(
        self,
        config: AIEngineConfig,
        api_key: str,
        credential_available: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("配置小说画面提取助手")
        self.resize(680, 470)
        self._loading = True
        self._refresh_thread: QThread | None = None
        self._refresh_worker: AIModelListWorker | None = None

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "小说画面提取助手只提取正文中可见的人物、服饰、动作和场景，写成可编辑的中文画面稿。"
            "翻译、标签匹配和质量增强仍由本地 Marian / 离线引擎完成，不会让模型直接写 ANIMA Prompt。"
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet(
            "background: #eef4ff; color: #234a83; border: 1px solid #c9daf8; "
            "border-radius: 5px; padding: 8px;"
        )
        layout.addWidget(explanation)

        form = QFormLayout()
        self.provider = QComboBox()
        self.provider.addItem("OpenCode Go 套餐", "opencode_go")
        self.provider.addItem("OpenAI 兼容接口", "openai_compatible")
        form.addRow("服务商", self.provider)

        self.base_url = QLineEdit()
        form.addRow("API Base URL", self.base_url)

        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        self.model = QComboBox()
        self.model.setEditable(True)
        self._set_model_items(OPENCODE_GO_KNOWN_MODELS)
        model_layout.addWidget(self.model, 1)
        self.refresh_models_button = QPushButton("刷新模型列表")
        self.refresh_models_button.clicked.connect(self.refresh_models)
        model_layout.addWidget(self.refresh_models_button)
        form.addRow("模型", model_row)

        self.model_cost_hint = QLabel(
            "★ 限时免费：OpenCode 当前免费模型；⚠ 较贵 / 高消耗：官方估算每 5 小时不超过 1,000 次请求。"
            "提取任务建议用 mimo-v2.5 一类较快的模型。"
        )
        self.model_cost_hint.setWordWrap(True)
        self.model_cost_hint.setStyleSheet("color: #805b10")
        form.addRow("标识说明", self.model_cost_hint)

        self.api_style = QComboBox()
        self.api_style.addItem("自动识别（推荐）", AIAPIStyle.AUTO.value)
        self.api_style.addItem("OpenAI Chat Completions", AIAPIStyle.CHAT_COMPLETIONS.value)
        self.api_style.addItem("OpenAI Responses", AIAPIStyle.RESPONSES.value)
        self.api_style.addItem("Anthropic Messages", AIAPIStyle.MESSAGES.value)
        form.addRow("接口协议", self.api_style)
        self.resolved_protocol = QLabel()
        self.resolved_protocol.setStyleSheet("color: #666")
        form.addRow("实际调用", self.resolved_protocol)

        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        self.api_key = QLineEdit(api_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        key_layout.addWidget(self.api_key, 1)
        self.remember_key = QCheckBox("安全记住")
        self.remember_key.setChecked(bool(api_key))
        self.remember_key.setEnabled(credential_available)
        self.remember_key.setToolTip("保存到 Windows 凭据管理器，不写入项目数据库。")
        key_layout.addWidget(self.remember_key)
        form.addRow("API Key", key_row)

        self.thinking = QCheckBox("使用思考（更慢，提取场景时通常不需要）")
        self.thinking.setChecked(config.thinking_enabled)
        form.addRow("思考", self.thinking)

        self.timeout = QSpinBox()
        self.timeout.setRange(10, 600)
        self.timeout.setSuffix(" 秒")
        form.addRow("请求超时", self.timeout)
        layout.addLayout(form)

        privacy = QLabel("只有点击「开始提取」时才会把粘贴的文本发给所选服务商。主界面的「翻译并编译」始终走本地引擎。")
        privacy.setWordWrap(True)
        privacy.setStyleSheet("color: #666")
        layout.addWidget(privacy)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.provider.setCurrentIndex(self.provider.findData(config.provider_id))
        self.base_url.setText(config.base_url)
        self.set_model_id(config.model)
        self.api_style.setCurrentIndex(self.api_style.findData(config.api_style.value))
        self.timeout.setValue(config.timeout_seconds)
        self._loading = False
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.model.currentTextChanged.connect(self._update_resolved_protocol)
        self.api_style.currentIndexChanged.connect(self._update_resolved_protocol)
        self.base_url.textChanged.connect(self._update_resolved_protocol)
        self._provider_changed()
        if config.provider_id != "opencode_go":
            self.base_url.setText(config.base_url)
        self.set_model_id(config.model)
        self.api_style.setCurrentIndex(self.api_style.findData(config.api_style.value))
        self.thinking.setChecked(config.thinking_enabled)
        self._update_resolved_protocol()

    def _provider_changed(self) -> None:
        is_go = self.provider.currentData() == "opencode_go"
        self.base_url.setReadOnly(is_go)
        self.model_cost_hint.setVisible(is_go)
        if is_go:
            self.base_url.setText(OPENCODE_GO_BASE_URL)
            current = self.model_id()
            self._set_model_items(OPENCODE_GO_KNOWN_MODELS)
            self.set_model_id(
                current if current in OPENCODE_GO_KNOWN_MODELS else OPENCODE_GO_KNOWN_MODELS[1]
            )
        else:
            current = self.model_id()
            self._set_model_items([current] if current else [])
            if current:
                self.set_model_id(current)
            if self.base_url.text().strip() == OPENCODE_GO_BASE_URL:
                self.base_url.setText("https://api.openai.com/v1")
        self._update_resolved_protocol()

    def _update_resolved_protocol(self) -> None:
        try:
            config = self.engine_config()
            labels = {
                AIAPIStyle.CHAT_COMPLETIONS: "/chat/completions",
                AIAPIStyle.RESPONSES: "/responses",
                AIAPIStyle.MESSAGES: "/messages",
            }
            self.resolved_protocol.setText(labels[config.resolved_style()])
        except Exception:
            self.resolved_protocol.setText("等待完整配置")

    def engine_config(self) -> AIEngineConfig:
        return AIEngineConfig(
            provider_id=self.provider.currentData(),
            base_url=self.base_url.text(),
            model=self.model_id(),
            api_style=self.api_style.currentData(),
            timeout_seconds=self.timeout.value(),
            thinking_enabled=self.thinking.isChecked(),
        )

    def refresh_models(self) -> None:
        if self._refresh_worker is not None:
            return
        try:
            config = self.engine_config()
            key = self.api_key.text().strip()
            worker = AIModelListWorker(client=AIClient(config, key))
        except Exception as exc:
            QMessageBox.critical(self, "刷新模型失败", str(exc))
            return
        self.refresh_models_button.setEnabled(False)
        self.refresh_models_button.setText("正在刷新…")
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._models_refreshed)
        worker.failed.connect(lambda message: QMessageBox.critical(self, "刷新模型失败", message))
        worker.done.connect(self._refresh_finished)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._refresh_thread = thread
        self._refresh_worker = worker
        thread.start()

    def _models_refreshed(self, models: list[str]) -> None:
        if not models:
            QMessageBox.warning(self, "刷新模型失败", "服务商没有返回可用模型。")
            return
        current = self.model_id()
        self._set_model_items(models)
        self.set_model_id(current if current in models else models[0])

    def _refresh_finished(self) -> None:
        self._refresh_worker = None
        self._refresh_thread = None
        self.refresh_models_button.setEnabled(True)
        self.refresh_models_button.setText("刷新模型列表")

    def _set_model_items(self, model_ids: list[str]) -> None:
        self.model.clear()
        is_go = self.provider.currentData() == "opencode_go" if hasattr(self, "provider") else True
        for model_id in model_ids:
            label = opencode_go_model_label(model_id) if is_go else model_id
            self.model.addItem(label, model_id)

    def model_id(self) -> str:
        index = self.model.currentIndex()
        if index >= 0 and self.model.currentText() == self.model.itemText(index):
            data = self.model.itemData(index)
            if data:
                return str(data).strip()
        return self.model.currentText().strip()

    def set_model_id(self, model_id: str) -> None:
        index = self.model.findData(model_id)
        if index >= 0:
            self.model.setCurrentIndex(index)
        else:
            self.model.setEditText(model_id)

    def accept(self) -> None:
        try:
            self.engine_config()
            if not self.api_key.text().strip():
                raise ValueError("请填写 API Key。")
        except Exception as exc:
            QMessageBox.warning(self, "配置不完整", str(exc))
            return
        super().accept()
