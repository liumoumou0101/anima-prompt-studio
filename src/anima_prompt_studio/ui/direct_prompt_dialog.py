from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTextEdit, QVBoxLayout,
)


class DirectPromptDialog(QDialog):
    """Collect already-compiled prompts without passing them through the local compiler."""

    def __init__(
        self,
        *,
        draft: dict | None = None,
        current_positive: str = "",
        current_negative: str = "",
        generation_summary: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("提示词直出")
        self.resize(920, 680)
        draft = draft or {}

        layout = QVBoxLayout(self)
        tip = QLabel(
            "这里的内容会原样写入 ComfyUI 的正向和反向提示词节点，不经过翻译、标签匹配、"
            "质量词补充或自动重编译。模型、工作流、LoRA 和生成参数沿用主界面当前设置。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(
            "background:#fff6df;color:#6b4b00;border:1px solid #ead59d;"
            "border-radius:5px;padding:8px;"
        )
        layout.addWidget(tip)

        form = QFormLayout()
        self.project_name = QLineEdit(str(draft.get("project_name") or "外部提示词直出"))
        form.addRow("任务名称", self.project_name)
        layout.addLayout(form)

        layout.addWidget(QLabel("正向提示词"))
        self.positive = QTextEdit()
        self.positive.setPlaceholderText("粘贴 UP 主分享的完整正向提示词")
        self.positive.setPlainText(str(draft.get("positive_prompt") or ""))
        layout.addWidget(self.positive, 3)

        layout.addWidget(QLabel("反向提示词"))
        self.negative = QTextEdit()
        self.negative.setPlaceholderText("粘贴完整反向提示词；允许留空")
        self.negative.setPlainText(str(draft.get("negative_prompt") or ""))
        layout.addWidget(self.negative, 2)

        summary = QLabel(generation_summary)
        summary.setWordWrap(True)
        summary.setStyleSheet("color:#555;padding:4px")
        layout.addWidget(summary)

        buttons = QHBoxLayout()
        load_current = QPushButton("载入主界面当前提示词")
        load_current.clicked.connect(
            lambda: self._load_current(current_positive, current_negative)
        )
        clear = QPushButton("清空")
        clear.clicked.connect(self._clear_prompts)
        generate = QPushButton("使用这些提示词生图")
        generate.setProperty("buttonRole", "success")
        generate.clicked.connect(self._accept_generation)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(load_current)
        buttons.addWidget(clear)
        buttons.addStretch()
        buttons.addWidget(generate)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _load_current(self, positive: str, negative: str) -> None:
        self.positive.setPlainText(positive)
        self.negative.setPlainText(negative)

    def _clear_prompts(self) -> None:
        self.positive.clear()
        self.negative.clear()

    def _accept_generation(self) -> None:
        if not self.positive.toPlainText().strip():
            QMessageBox.information(self, "正向提示词为空", "请先粘贴正向提示词。")
            return
        self.accept()

    def result_payload(self) -> dict[str, str]:
        return {
            "project_name": self.project_name.text().strip() or "外部提示词直出",
            "positive_prompt": self.positive.toPlainText(),
            "negative_prompt": self.negative.toPlainText(),
        }
