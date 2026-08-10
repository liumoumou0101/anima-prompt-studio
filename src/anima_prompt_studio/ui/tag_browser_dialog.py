"""Browse built-in tags by category for prompt inspiration."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QHeaderView,
)

# Display order and Chinese labels for inspiration browsing.
CATEGORY_LABELS: list[tuple[str, str]] = [
    ("all", "全部"),
    ("count", "人数"),
    ("hair", "发色"),
    ("hair_length", "发长"),
    ("style", "发型/造型"),
    ("eyes", "瞳色/眼睛"),
    ("expression", "表情"),
    ("pose", "姿势/构图辅助"),
    ("gaze", "视线"),
    ("shot", "景别"),
    ("camera", "机位/镜头"),
    ("angle", "角度"),
    ("clothing", "服装/配饰"),
    ("state", "身体/状态"),
    ("act", "动作/行为"),
    ("race", "种族/身份"),
    ("scene", "场景"),
    ("time", "时间"),
    ("weather", "天气"),
    ("lighting", "光线"),
    ("general", "其他"),
]


def category_display(category: str) -> str:
    for key, label in CATEGORY_LABELS:
        if key == category:
            return label
    return category


class TagBrowserDialog(QDialog):
    """Categorized viewer for configs/tags.json (built-in vocabulary)."""

    def __init__(self, parent=None, tags_path: Path | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("内置标签浏览 · 灵感库")
        self.resize(980, 620)
        self.tags_path = tags_path or Path(__file__).resolve().parent.parent / "configs" / "tags.json"
        self.entries: list[dict] = self._load_tags()
        self._build_ui()
        self._populate_categories()
        self.refresh_table()

    def _load_tags(self) -> list[dict]:
        if not self.tags_path.is_file():
            return []
        try:
            data = json.loads(self.tags_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tip = QLabel(
            "以下为软件内置中英标签词表（非完整 Danbooru 库）。"
            "可按分类浏览、搜索；双击或点按钮复制标签到剪贴板，方便写提示词时找灵感。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #555; margin-bottom: 4px;")
        layout.addWidget(tip)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("分类"))
        self.category_combo = QComboBox()
        self.category_combo.currentIndexChanged.connect(self.refresh_table)
        filters.addWidget(self.category_combo)
        filters.addWidget(QLabel("搜索"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("英文标签 / 中文触发词…")
        self.search_edit.textChanged.connect(self.refresh_table)
        filters.addWidget(self.search_edit, 1)
        self.count_label = QLabel("")
        filters.addWidget(self.count_label)
        layout.addLayout(filters)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["标签 (EN)", "分类", "中文触发词", "英文同义词"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self.copy_selected_tag)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        copy_tag = QPushButton("复制英文标签")
        copy_tag.clicked.connect(self.copy_selected_tag)
        copy_zh = QPushButton("复制中文触发词")
        copy_zh.clicked.connect(self.copy_selected_zh)
        copy_line = QPushButton("复制「中文 → 标签」")
        copy_line.clicked.connect(self.copy_selected_line)
        buttons.addWidget(copy_tag)
        buttons.addWidget(copy_zh)
        buttons.addWidget(copy_line)
        buttons.addStretch()
        close_box = QDialogButtonBox(QDialogButtonBox.Close)
        close_box.rejected.connect(self.reject)
        close_box.accepted.connect(self.accept)
        buttons.addWidget(close_box)
        layout.addLayout(buttons)

    def _populate_categories(self) -> None:
        present = {str(e.get("category") or "general") for e in self.entries}
        self.category_combo.clear()
        for key, label in CATEGORY_LABELS:
            if key == "all" or key in present:
                count = len(self.entries) if key == "all" else sum(
                    1 for e in self.entries if str(e.get("category") or "general") == key
                )
                self.category_combo.addItem(f"{label} ({count})", key)
        # Any unknown categories
        known = {k for k, _ in CATEGORY_LABELS}
        for cat in sorted(present - known):
            count = sum(1 for e in self.entries if str(e.get("category") or "general") == cat)
            self.category_combo.addItem(f"{cat} ({count})", cat)

    def _filtered(self) -> list[dict]:
        cat = self.category_combo.currentData() or "all"
        query = self.search_edit.text().strip().lower()
        rows: list[dict] = []
        for entry in self.entries:
            entry_cat = str(entry.get("category") or "general")
            if cat != "all" and entry_cat != cat:
                continue
            tag = str(entry.get("tag") or "")
            zh = " ".join(entry.get("zh") or [])
            en = " ".join(entry.get("en") or [])
            blob = f"{tag} {zh} {en} {entry_cat}".lower()
            if query and query not in blob:
                continue
            rows.append(entry)
        rows.sort(key=lambda e: (str(e.get("category") or ""), str(e.get("tag") or "")))
        return rows

    def refresh_table(self) -> None:
        rows = self._filtered()
        self.table.setRowCount(len(rows))
        for row, entry in enumerate(rows):
            tag = str(entry.get("tag") or "")
            cat = str(entry.get("category") or "general")
            zh = "、".join(entry.get("zh") or [])
            en = ", ".join(entry.get("en") or [])
            items = [
                QTableWidgetItem(tag),
                QTableWidgetItem(category_display(cat)),
                QTableWidgetItem(zh),
                QTableWidgetItem(en),
            ]
            for col, item in enumerate(items):
                item.setData(Qt.UserRole, entry)
                self.table.setItem(row, col, item)
        self.count_label.setText(f"显示 {len(rows)} / 共 {len(self.entries)}")

    def _current_entry(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def copy_selected_tag(self) -> None:
        entry = self._current_entry()
        if not entry:
            QMessageBox.information(self, "提示", "请先选中一行标签。")
            return
        text = str(entry.get("tag") or "")
        QGuiApplication.clipboard().setText(text)
        self.setWindowTitle(f"内置标签浏览 · 已复制：{text}")

    def copy_selected_zh(self) -> None:
        entry = self._current_entry()
        if not entry:
            QMessageBox.information(self, "提示", "请先选中一行标签。")
            return
        zh = "、".join(entry.get("zh") or [])
        if not zh:
            QMessageBox.information(self, "提示", "该标签没有中文触发词。")
            return
        QGuiApplication.clipboard().setText(zh)
        self.setWindowTitle(f"内置标签浏览 · 已复制中文：{zh[:40]}")

    def copy_selected_line(self) -> None:
        entry = self._current_entry()
        if not entry:
            QMessageBox.information(self, "提示", "请先选中一行标签。")
            return
        tag = str(entry.get("tag") or "")
        zh = "、".join(entry.get("zh") or []) or "(无中文)"
        text = f"{zh} → {tag}"
        QGuiApplication.clipboard().setText(text)
        self.setWindowTitle(f"内置标签浏览 · 已复制：{text[:50]}")
