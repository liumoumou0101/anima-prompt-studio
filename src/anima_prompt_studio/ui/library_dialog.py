from __future__ import annotations

import re
from typing import Any

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPushButton, QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from anima_prompt_studio.domain.models import ArtistProfile, CharacterCard, LoRAProfile
from anima_prompt_studio.repositories import SQLiteRepository


def split_values(text: str) -> list[str]:
    return [x.strip() for x in text.replace("，", ",").split(",") if x.strip()]


def make_id(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip()).strip("_").lower()
    return value or "item"


class LibraryPanel(QWidget):
    def __init__(self, repository: SQLiteRepository, model_type: type, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.model_type = model_type
        self.entities: list[Any] = []
        self.selected_entity = None
        outer = QVBoxLayout(self)
        split = QSplitter()
        left = QWidget(); ll = QVBoxLayout(left)
        self.list = QListWidget(); self.list.currentRowChanged.connect(self.load_row); ll.addWidget(self.list)
        new_button = QPushButton("新建"); new_button.clicked.connect(self.clear_form); ll.addWidget(new_button)
        split.addWidget(left)
        right = QWidget(); self.form = QFormLayout(right); self.fields: dict[str, QWidget] = {}
        self._build_form()
        split.addWidget(right); split.setSizes([220, 520]); outer.addWidget(split)
        buttons = QHBoxLayout()
        save = QPushButton("保存到库"); save.clicked.connect(self.save)
        use = QPushButton("应用到当前任务"); use.clicked.connect(self.use_selected)
        buttons.addStretch(); buttons.addWidget(save); buttons.addWidget(use); outer.addLayout(buttons)
        self.reload()

    def _line(self, key: str, label: str, placeholder: str = "") -> QLineEdit:
        widget = QLineEdit(); widget.setPlaceholderText(placeholder); self.fields[key] = widget; self.form.addRow(label, widget); return widget

    def _text(self, key: str, label: str) -> QTextEdit:
        widget = QTextEdit(); widget.setMaximumHeight(72); self.fields[key] = widget; self.form.addRow(label, widget); return widget

    def _build_form(self) -> None:
        self._line("id", "ID")
        self._line("display_name", "显示名")
        self._line("aliases", "别名", "逗号分隔")
        if self.model_type is CharacterCard:
            gender = QComboBox(); gender.addItems(["1girl", "1boy", "1other"]); self.fields["gender_tag"] = gender; self.form.addRow("性别标签", gender)
            self._line("identity_tags", "身份标签", "逗号分隔")
            self._line("default_appearance_tags", "默认外观", "逗号分隔")
            self._line("default_clothing_tags", "默认服装", "逗号分隔")
            self._line("optional_tags", "可选标签", "逗号分隔")
            self._line("anima_character_tag", "ANIMA 角色标签")
        elif self.model_type is ArtistProfile:
            self._line("canonical_tag", "标准标签")
            self._line("output_tag", "输出标签", "@artist name")
            self._line("historical_tags", "历史标签", "逗号分隔")
            self._line("style_keywords", "风格关键词", "逗号分隔")
        else:
            self._line("file_name", "文件名", "example.safetensors")
            self._line("default_weight", "默认权重", "0.8")
            self._line("trigger_words", "触发词", "逗号分隔")
            kind = QComboBox(); kind.addItems(["character", "style", "pose", "detail"]); self.fields["type"] = kind; self.form.addRow("类型", kind)
            conflict = QComboBox(); conflict.addItems(["否", "是"]); self.fields["conflicts_with_artist_style"] = conflict; self.form.addRow("与画师风格冲突", conflict)
        self._text("notes", "备注")

    def reload(self) -> None:
        self.entities = self.repository.list_entities(self.model_type)
        self.list.clear()
        for entity in self.entities: self.list.addItem(entity.display_name)

    def clear_form(self) -> None:
        self.list.clearSelection(); self.selected_entity = None
        for widget in self.fields.values():
            if isinstance(widget, QLineEdit): widget.clear()
            elif isinstance(widget, QTextEdit): widget.clear()
            elif isinstance(widget, QComboBox): widget.setCurrentIndex(0)

    def load_row(self, row: int) -> None:
        if row < 0 or row >= len(self.entities): return
        entity = self.entities[row]; self.selected_entity = entity
        data = entity.model_dump()
        for key, widget in self.fields.items():
            value = data.get(key, "")
            if isinstance(value, list): value = ", ".join(value)
            if isinstance(widget, QLineEdit): widget.setText("" if value is None else str(value))
            elif isinstance(widget, QTextEdit): widget.setPlainText(str(value or ""))
            elif isinstance(widget, QComboBox):
                if key == "conflicts_with_artist_style": widget.setCurrentIndex(1 if value else 0)
                else: widget.setCurrentText(str(value))

    def _value(self, key: str):
        widget = self.fields[key]
        if isinstance(widget, QLineEdit): return widget.text().strip()
        if isinstance(widget, QTextEdit): return widget.toPlainText().strip()
        if isinstance(widget, QComboBox): return widget.currentText()

    def build_entity(self):
        display_name = self._value("display_name")
        if not display_name: raise ValueError("显示名不能为空。")
        common = dict(id=self._value("id") or make_id(display_name), display_name=display_name, aliases=split_values(self._value("aliases")), notes=self._value("notes"))
        if self.model_type is CharacterCard:
            return CharacterCard(**common, gender_tag=self._value("gender_tag"), identity_tags=split_values(self._value("identity_tags")),
                default_appearance_tags=split_values(self._value("default_appearance_tags")), default_clothing_tags=split_values(self._value("default_clothing_tags")),
                optional_tags=split_values(self._value("optional_tags")), anima_character_tag=self._value("anima_character_tag") or None)
        if self.model_type is ArtistProfile:
            canonical = self._value("canonical_tag") or display_name
            return ArtistProfile(**common, canonical_tag=canonical, output_tag=self._value("output_tag") or f"@{canonical}",
                historical_tags=split_values(self._value("historical_tags")), style_keywords=split_values(self._value("style_keywords")))
        try: weight = float(self._value("default_weight") or .8)
        except ValueError: raise ValueError("LoRA 默认权重必须是数字。")
        return LoRAProfile(**common, file_name=self._value("file_name") or f"{common['id']}.safetensors", default_weight=weight,
            trigger_words=split_values(self._value("trigger_words")), type=self._value("type"), conflicts_with_artist_style=self._value("conflicts_with_artist_style") == "是")

    def save(self) -> None:
        try:
            entity = self.build_entity(); self.repository.save_entity(entity); self.selected_entity = entity; self.reload()
            for row, item in enumerate(self.entities):
                if item.id == entity.id: self.list.setCurrentRow(row); break
        except Exception as exc: QMessageBox.warning(self, "无法保存", str(exc))

    def use_selected(self) -> None:
        try:
            self.selected_entity = self.build_entity()
            self.window().accept()
        except Exception as exc: QMessageBox.warning(self, "无法应用", str(exc))


class EntityLibraryDialog(QDialog):
    def __init__(self, repository: SQLiteRepository, initial: type = CharacterCard, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("角色、画师与 LoRA 库")
        self.resize(850, 590)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        self.panels = {
            CharacterCard: LibraryPanel(repository, CharacterCard),
            ArtistProfile: LibraryPanel(repository, ArtistProfile),
            LoRAProfile: LibraryPanel(repository, LoRAProfile),
        }
        for model, label in ((CharacterCard,"角色卡"),(ArtistProfile,"画师库"),(LoRAProfile,"LoRA 库")):
            self.tabs.addTab(self.panels[model], label)
        self.tabs.setCurrentWidget(self.panels[initial])

    @property
    def selected_entity(self):
        return self.tabs.currentWidget().selected_entity

