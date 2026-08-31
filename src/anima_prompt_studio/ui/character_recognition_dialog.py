from __future__ import annotations

import re

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from anima_prompt_studio.domain.models import CharacterCard
from anima_prompt_studio.repositories.tag_database import TagDatabase
from anima_prompt_studio.services.ai_prompt_service import AIClient, AIEngineConfig
from anima_prompt_studio.services.character_resolution import CharacterRecognitionService, CharacterSuggestion
from anima_prompt_studio.services.remote.credential_store import CredentialStore
from anima_prompt_studio.ui.ai_engine_dialog import AIEngineDialog
from anima_prompt_studio.ui.ai_workers import CharacterRecognitionWorker


class CharacterRecognitionDialog(QDialog):
    config_saved = Signal(object, str, bool)

    def __init__(
        self,
        *,
        source_text: str,
        database: TagDatabase,
        config: AIEngineConfig,
        api_key: str,
        credential_store: CredentialStore,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("识别中文角色名")
        self.resize(1050, 480)
        self.source_text = source_text
        self.database = database
        self.config = config
        self.api_key = api_key
        self.credential_store = credential_store
        self.suggestions: list[CharacterSuggestion] = []
        self.selected_cards: list[CharacterCard] = []
        self._thread: QThread | None = None
        self._worker: CharacterRecognitionWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tip = QLabel(
            "AI 只负责把中文名转换为候选英文名；最终角色和作品标签必须存在于本地 ANIMA 标签库。"
            "确认后映射会保存到角色卡，以后输入同一中文名时完全离线匹配。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("background:#eef4ff;color:#234a83;border:1px solid #c9daf8;border-radius:5px;padding:8px;")
        layout.addWidget(tip)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["保存", "输入中的名字", "本地角色标签", "本地作品标签", "性别"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.status = QLabel("点击“开始识别”。没有配置 API Key 时会先打开设置。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        settings = QPushButton("配置 API…")
        settings.clicked.connect(self.configure_engine)
        self.recognize_button = QPushButton("开始识别")
        self.recognize_button.setProperty("buttonRole", "primary")
        self.recognize_button.clicked.connect(self.start_recognition)
        save = QPushButton("保存映射并应用")
        save.clicked.connect(self.accept_cards)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        buttons.addWidget(settings)
        buttons.addWidget(self.recognize_button)
        buttons.addStretch()
        buttons.addWidget(save)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def configure_engine(self) -> bool:
        dialog = AIEngineDialog(self.config, self.api_key, self.credential_store.available, self)
        if dialog.exec() != QDialog.Accepted:
            return False
        self.config = dialog.engine_config()
        self.api_key = dialog.api_key.text().strip()
        self.config_saved.emit(self.config, self.api_key, dialog.remember_key.isChecked())
        return True

    def start_recognition(self) -> None:
        if self._worker is not None:
            return
        if not self.source_text.strip():
            QMessageBox.information(self, "没有输入", "请先在主界面输入包含角色名的描述。")
            return
        if not self.database.available:
            QMessageBox.warning(self, "本地标签库不可用", "请先安装标签资源；无法验证的 AI 候选不会被保存。")
            return
        if not self.api_key.strip() and not self.configure_engine():
            return
        try:
            client = AIClient(self.config, self.api_key)
        except Exception as exc:
            QMessageBox.critical(self, "无法开始识别", str(exc))
            return
        worker = CharacterRecognitionWorker(
            service=CharacterRecognitionService(self.database), client=client, source_text=self.source_text,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        worker.done.connect(self._done)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._worker = worker
        self._thread = thread
        self.recognize_button.setEnabled(False)
        self.recognize_button.setText("正在识别…")
        self.status.setText("正在获取名称候选并查询本地标签库…")
        thread.start()

    def _succeeded(self, suggestions: list[CharacterSuggestion]) -> None:
        self.suggestions = suggestions
        self._populate()
        validated = sum(bool(item.character_candidates) for item in suggestions)
        if not suggestions:
            self.status.setText("AI 没有找到明确的既有角色名。")
        else:
            self.status.setText(f"找到 {len(suggestions)} 个名字，其中 {validated} 个有本地角色标签候选。请确认后保存。")

    def _failed(self, message: str) -> None:
        QMessageBox.critical(self, "角色识别失败", message)
        self.status.setText("识别失败，未保存任何映射。")

    def _done(self) -> None:
        self._worker = None
        self._thread = None
        self.recognize_button.setEnabled(True)
        self.recognize_button.setText("重新识别")

    def _populate(self) -> None:
        self.table.setRowCount(len(self.suggestions))
        for row, suggestion in enumerate(self.suggestions):
            enabled = QCheckBox()
            enabled.setChecked(bool(suggestion.character_candidates))
            enabled.setEnabled(bool(suggestion.character_candidates))
            self.table.setCellWidget(row, 0, enabled)
            self.table.setItem(row, 1, QTableWidgetItem(suggestion.mention.source_text))
            character_box = QComboBox()
            for candidate in suggestion.character_candidates:
                character_box.addItem(
                    f"{candidate.output_name} · {candidate.post_count:,}", candidate.model_dump(),
                )
            if not suggestion.character_candidates:
                character_box.addItem("没有通过本地标签库验证的候选", None)
            self.table.setCellWidget(row, 2, character_box)
            copyright_box = QComboBox()
            for candidate in suggestion.copyright_candidates:
                copyright_box.addItem(
                    f"{candidate.output_name} · {candidate.post_count:,}", candidate.model_dump(),
                )
            copyright_box.addItem("（不添加作品标签）", None)
            self.table.setCellWidget(row, 3, copyright_box)
            gender = QComboBox()
            gender.addItem("女 / 1girl", "1girl")
            gender.addItem("男 / 1boy", "1boy")
            gender.addItem("其他 / 1other", "1other")
            mapping = {"girl": "1girl", "female": "1girl", "boy": "1boy", "male": "1boy", "other": "1other"}
            gender.setCurrentIndex(max(0, gender.findData(mapping.get(suggestion.mention.gender, "1other"))))
            self.table.setCellWidget(row, 4, gender)

    def accept_cards(self) -> None:
        cards: list[CharacterCard] = []
        for row, suggestion in enumerate(self.suggestions):
            enabled = self.table.cellWidget(row, 0)
            character_box = self.table.cellWidget(row, 2)
            copyright_box = self.table.cellWidget(row, 3)
            gender = self.table.cellWidget(row, 4)
            if not isinstance(enabled, QCheckBox) or not enabled.isChecked() or not isinstance(character_box, QComboBox):
                continue
            character = character_box.currentData()
            if not character:
                continue
            copyright = copyright_box.currentData() if isinstance(copyright_box, QComboBox) else None
            canonical = str(character["canonical_name"])
            card_id = "character_" + re.sub(r"[^a-z0-9]+", "_", canonical.casefold()).strip("_")
            aliases = list(dict.fromkeys(filter(None, [
                suggestion.mention.source_text,
                suggestion.mention.name_en,
                str(character["output_name"]),
            ])))
            cards.append(CharacterCard(
                id=card_id,
                display_name=suggestion.mention.source_text,
                aliases=aliases,
                entity_type="known_character",
                gender_tag=str(gender.currentData() if isinstance(gender, QComboBox) else "1girl"),
                anima_character_tag=canonical,
                copyright_tag=str(copyright["canonical_name"]) if copyright else None,
                notes="由角色识别助手生成；角色与作品标签已通过本地标签库验证。",
            ))
        if not cards:
            QMessageBox.information(self, "没有可保存的映射", "请至少勾选一个有本地标签候选的角色。")
            return
        self.selected_cards = cards
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._thread is not None and self._thread.isRunning():
            event.ignore()
            QMessageBox.information(self, "正在识别", "请等待当前识别完成后再关闭。")
            return
        super().closeEvent(event)
