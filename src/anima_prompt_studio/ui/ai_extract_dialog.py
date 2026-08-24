from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from anima_prompt_studio.services.ai_extract_service import (
    AIExtractService,
    ExtractedPrompt,
    MAX_SOURCE_CHARS,
)
from anima_prompt_studio.services.ai_prompt_service import AIClient, AIEngineConfig
from anima_prompt_studio.services.remote.credential_store import CredentialStore
from anima_prompt_studio.ui.ai_engine_dialog import AIEngineDialog
from anima_prompt_studio.ui.ai_workers import AIExtractWorker


class AIExtractDialog(QDialog):
    applied = Signal(str, str)
    direct_compile_requested = Signal(object)
    config_saved = Signal(object, str, bool)

    def __init__(
        self,
        *,
        config: AIEngineConfig,
        api_key: str,
        credential_store: CredentialStore,
        current_zh: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("小说画面提取助手")
        self.resize(1080, 720)
        self.config = config
        self.api_key = api_key
        self.credential_store = credential_store
        self._current_zh = current_zh
        self.result: ExtractedPrompt | None = None
        self._thread: QThread | None = None
        self._worker: AIExtractWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tip = QLabel(
            "把小说正文粘在左侧。助手只抽取同一画面中可见的人物外貌、服装、饰品、鞋类、"
            "动作和场景。普通写入仍可使用原有流程；复杂场景建议选择独立的画面计划编译。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(
            "background:#eef4ff;color:#234a83;border:1px solid #c9daf8;"
            "border-radius:5px;padding:8px;"
        )
        layout.addWidget(tip)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        source_panel = QVBoxLayout(left)
        source_panel.addWidget(QLabel("原文"))
        self.source = QTextEdit()
        self.source.setPlaceholderText("在这里粘贴长文本。超过约 8000 字会截断后提取。")
        if self._current_zh.strip():
            self.source.setPlainText(self._current_zh)
        source_panel.addWidget(self.source, 1)
        source_buttons = QHBoxLayout()
        load_input = QPushButton("载入当前输入区")
        load_input.clicked.connect(self._load_current_input)
        load_file = QPushButton("打开文本文件…")
        load_file.clicked.connect(self._load_file)
        source_buttons.addWidget(load_input)
        source_buttons.addWidget(load_file)
        source_buttons.addStretch()
        source_panel.addLayout(source_buttons)

        right = QWidget()
        result_panel = QVBoxLayout(right)
        result_panel.addWidget(QLabel("提取结果（取消勾选可排除）"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["项目", "内容"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.itemChanged.connect(self._tree_changed)
        result_panel.addWidget(self.tree, 2)
        result_panel.addWidget(QLabel("ANIMA 编译稿（已压缩、去重并按人物分区）"))
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        result_panel.addWidget(self.preview, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self.status = QLabel(self._status_text())
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#555")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.settings_button = QPushButton("配置 API…")
        self.settings_button.clicked.connect(self.configure_engine)
        self.extract_button = QPushButton("开始提取")
        self.extract_button.setProperty("buttonRole", "primary")
        self.extract_button.clicked.connect(self.start_extract)
        replace_button = QPushButton("替换写入输入区")
        replace_button.clicked.connect(lambda: self._apply("replace"))
        append_button = QPushButton("追加到输入区")
        append_button.clicked.connect(lambda: self._apply("append"))
        compile_button = QPushButton("写入并翻译编译")
        compile_button.setText("写入并按画面计划编译")
        compile_button.setToolTip("使用小说助手的冻结画面英文计划；不经过旧 Marian 多人翻译链路。")
        compile_button.clicked.connect(self._apply_direct)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(self.settings_button)
        buttons.addWidget(self.extract_button)
        buttons.addStretch()
        buttons.addWidget(replace_button)
        buttons.addWidget(append_button)
        buttons.addWidget(compile_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _status_text(self) -> str:
        thinking = "开" if self.config.thinking_enabled else "关"
        return (
            f"当前：{self.config.model} · 思考{thinking} · 超时 {self.config.timeout_seconds} 秒。"
            "未配置 Key 时会先打开设置。"
        )

    def _load_current_input(self) -> None:
        if not self._current_zh.strip():
            QMessageBox.information(self, "输入区是空的", "主界面中文输入区目前没有内容。")
            return
        self.source.setPlainText(self._current_zh)

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开文本", "", "文本 (*.txt *.md *.json);;所有文件 (*.*)")
        if not path:
            return
        try:
            self.source.setPlainText(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            QMessageBox.critical(self, "读取文件失败", str(exc))

    def configure_engine(self) -> bool:
        dialog = AIEngineDialog(self.config, self.api_key, self.credential_store.available, self)
        if dialog.exec() != QDialog.Accepted:
            return False
        self.config = dialog.engine_config()
        self.api_key = dialog.api_key.text().strip()
        self.config_saved.emit(self.config, self.api_key, dialog.remember_key.isChecked())
        self.status.setText(self._status_text())
        return True

    def start_extract(self) -> None:
        if self._worker is not None:
            return
        if not self.api_key.strip() and not self.configure_engine():
            return
        source = self.source.toPlainText().strip()
        if not source:
            QMessageBox.information(self, "没有原文", "请先粘贴或打开要提取的文本。")
            return
        if len(source) > MAX_SOURCE_CHARS:
            self.status.setText(f"原文超过 {MAX_SOURCE_CHARS} 字，将截断后提取。")
        try:
            client = AIClient(self.config, self.api_key)
        except Exception as exc:
            QMessageBox.critical(self, "无法开始提取", str(exc))
            return
        worker = AIExtractWorker(service=AIExtractService(), client=client, source_text=source)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._extract_succeeded)
        worker.failed.connect(self._extract_failed)
        worker.done.connect(self._extract_done)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._worker = worker
        self._thread = thread
        self.extract_button.setEnabled(False)
        self.extract_button.setText("正在提取…")
        self.status.setText("正在后台提取，主界面可以继续用。过长思考可在配置里关闭。")
        thread.start()

    def _extract_succeeded(self, result: ExtractedPrompt) -> None:
        self.result = result
        self._populate_tree(result)
        self._refresh_preview()
        extra = "原文已截断。" if result.truncated_source else ""
        self.status.setText(f"已提取 {len(result.selected_characters())} 名人物。请勾选需要的项后写入输入区。{extra}")

    def _extract_failed(self, message: str) -> None:
        QMessageBox.critical(self, "提取失败", message)
        self.status.setText("提取失败。可关闭思考、换较快的模型，或稍后重试。")

    def _extract_done(self) -> None:
        self._worker = None
        self._thread = None
        self.extract_button.setEnabled(True)
        self.extract_button.setText("开始提取")

    def _populate_tree(self, result: ExtractedPrompt) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        if result.summary_zh.strip():
            self._add_group("summary", "画面摘要", result.summary_zh.strip(), result.include_summary)
        for index, character in enumerate(result.characters):
            label = character.label.strip() or f"人物 {index + 1}"
            parent = self._add_group(f"character:{index}", f"人物 · {label}", character.to_clause(), character.included)
            self._add_detail(parent, "身份", character.identity)
            self._add_detail(parent, "外貌", "，".join(character.appearance))
            self._add_detail(parent, "体态", "，".join(character.body))
            self._add_detail(parent, "服装", "，".join(character.clothing))
            self._add_detail(parent, "饰品", "，".join(character.accessories))
            self._add_detail(parent, "鞋类", "，".join(character.footwear))
            self._add_detail(parent, "表情", character.expression)
            self._add_detail(parent, "视线", character.gaze)
            self._add_detail(parent, "姿势", character.pose)
            self._add_detail(parent, "动作", character.action)
        if result.scene.visible_facts():
            parent = self._add_group("scene", "场景", result.scene.to_clause(), result.scene.included)
            self._add_detail(parent, "地点", result.scene.location)
            self._add_detail(parent, "时间", result.scene.time)
            self._add_detail(parent, "天气", result.scene.weather)
            self._add_detail(parent, "物体", "，".join(result.scene.objects))
            self._add_detail(parent, "光线", result.scene.lighting)
            self._add_detail(parent, "氛围", result.scene.atmosphere)
        if result.camera.visible_facts():
            self._add_group("camera", "构图", result.camera.to_clause(), result.camera.included)
        if result.negatives:
            self._add_group("negatives", "不要画", "，".join(result.negatives), result.include_negatives)
        self.tree.expandAll()
        self.tree.blockSignals(False)

    def _add_group(self, key: str, title: str, detail: str, checked: bool) -> QTreeWidgetItem:
        item = QTreeWidgetItem([title, detail])
        item.setData(0, Qt.UserRole, key)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        self.tree.addTopLevelItem(item)
        return item

    @staticmethod
    def _add_detail(parent: QTreeWidgetItem, title: str, value: str) -> None:
        if not value.strip():
            return
        QTreeWidgetItem(parent, [title, value.strip()])

    def _tree_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self.result is None or column != 0 or item.parent() is not None:
            return
        key = str(item.data(0, Qt.UserRole) or "")
        included = item.checkState(0) == Qt.Checked
        if key == "summary":
            self.result.include_summary = included
        elif key.startswith("character:"):
            index = int(key.split(":", 1)[1])
            if 0 <= index < len(self.result.characters):
                self.result.characters[index].included = included
        elif key == "scene":
            self.result.scene.included = included
        elif key == "camera":
            self.result.camera.included = included
        elif key == "negatives":
            self.result.include_negatives = included
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if self.result is None:
            self.preview.clear()
            return
        self.preview.setPlainText(self.result.to_compiler_brief())

    def _apply(self, mode: str) -> None:
        brief = self.preview.toPlainText().strip()
        if not brief:
            QMessageBox.information(self, "没有可写入的画面稿", "请先提取，并至少勾选一项人物、姿势或场景。")
            return
        self.applied.emit(brief, mode)
        self.accept()

    def _apply_direct(self) -> None:
        if self.result is None or not self.result.direct_anima_prompt():
            QMessageBox.information(
                self,
                "没有可编译的画面计划",
                "请重新开始提取。旧格式结果仍可写入输入区，但不能使用复杂场景直编译。",
            )
            return
        self.direct_compile_requested.emit(self.result.model_copy(deep=True))
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._thread is not None and self._thread.isRunning():
            event.ignore()
            QMessageBox.information(self, "正在提取", "请等待当前提取结束后再关闭。")
            return
        super().closeEvent(event)
