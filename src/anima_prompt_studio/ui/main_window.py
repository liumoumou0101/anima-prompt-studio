from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSpinBox, QDoubleSpinBox,
    QSplitter, QStatusBar, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QToolBar, QVBoxLayout, QWidget,
)

from anima_prompt_studio.domain.models import (
    ArtistProfile, CharacterCard, CharacterSlot, CompositionFieldState, GenerationFieldState, ItemState,
    LoRAProfile, LoRASelection, PromptJob, SubjectMode,
)
from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio.services.export_service import ExportService
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.translation_service import LazyLocalMarianEngine, TranslationService, marian_runtime_available
from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.ui.library_dialog import EntityLibraryDialog
from anima_prompt_studio.ui.tag_browser_dialog import TagBrowserDialog

log = logging.getLogger(__name__)


class HistoryDialog(QDialog):
    def __init__(self, repository: SQLiteRepository, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("历史记录")
        self.resize(760, 460)
        self.repository = repository
        self.selected_id: str | None = None
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["收藏", "项目", "更新时间", "中文输入"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self.accept_selection)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.reload()

    def reload(self) -> None:
        rows = self.repository.list_jobs()
        self.table.setRowCount(len(rows))
        for row, data in enumerate(rows):
            values = ["★" if data["favorite"] else "", data["project_name"], data["updated_at"][:19], data["original_zh"][:80]]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, data["id"])
                self.table.setItem(row, col, item)

    def accept_selection(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.selected_id = self.table.item(row, 0).data(Qt.UserRole)
            self.accept()


class MainWindow(QMainWindow):
    def __init__(self, repository: SQLiteRepository | None = None) -> None:
        super().__init__()
        self.repository = repository or SQLiteRepository()
        self.configs = ConfigService()
        self.pipeline = PromptPipeline(configs=self.configs, lora_profiles=self.repository.list_entities(LoRAProfile))
        self.exporter = ExportService()
        self.job = PromptJob()
        self._updating = False
        self._cached_character_people_count = 1
        self.setWindowTitle("ANIMA 中文提示词辅助工具 V1.1")
        self.resize(1540, 940)
        self.setMinimumSize(1100, 720)
        self._build_ui()
        self._create_menu()
        self._load_configured_translation()
        self.pipeline.compiler.apply_model_defaults(self.job)
        self._load_job_into_ui()
        self.statusBar().showMessage(f"就绪 · 翻译引擎：{self.pipeline.translation.engine_name}")

    def _load_configured_translation(self) -> None:
        if not marian_runtime_available():
            log.info("本地 Marian 模型运行依赖未安装，使用内置离线基础翻译。")
            return
        zh_en = self.repository.get_setting("zh_en_model_path")
        en_zh = self.repository.get_setting("en_zh_model_path")
        resources = ResourceManager()
        if (not zh_en or not en_zh) and resources.models_available():
            zh_en = str(resources.model_path("zh_en"))
            en_zh = str(resources.model_path("en_zh"))
        if zh_en and en_zh:
            try:
                self.pipeline.translation = TranslationService(LazyLocalMarianEngine(Path(zh_en), Path(en_zh)))
            except Exception:
                log.exception("已配置的本地翻译模型加载失败")
                if resources.models_available():
                    self.pipeline.translation = TranslationService(LazyLocalMarianEngine(resources.model_path("zh_en"), resources.model_path("en_zh")))

    def _create_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        for text, slot, shortcut in (
            ("新建", self.new_job, "Ctrl+N"), ("保存", self.save_job, "Ctrl+S"),
            ("历史记录", self.open_history, "Ctrl+H"), ("导出任务 JSON", self.export_json, "Ctrl+E"),
        ):
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            file_menu.addAction(action)
        settings = self.menuBar().addMenu("设置")
        model_action = QAction("配置本地 Marian 翻译模型…", self)
        model_action.triggered.connect(self.configure_translation)
        settings.addAction(model_action)
        # 画廊预留给后续生图历史；标签页用于浏览内置词表找灵感。
        gallery_menu = self.menuBar().addMenu("画廊")
        gallery_placeholder = QAction("画廊功能即将推出…", self)
        gallery_placeholder.setEnabled(False)
        gallery_menu.addAction(gallery_placeholder)
        tags_menu = self.menuBar().addMenu("标签")
        browse_tags = QAction("浏览内置标签（灵感库）…", self)
        browse_tags.setShortcut("Ctrl+T")
        browse_tags.triggered.connect(self.open_tag_browser)
        tags_menu.addAction(browse_tags)

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(10, 8, 10, 8)

        header = QHBoxLayout()
        header.addWidget(QLabel("项目名"))
        self.project_name = QLineEdit("未命名项目")
        self.project_name.setMaximumWidth(260)
        header.addWidget(self.project_name)
        header.addWidget(QLabel("模型"))
        self.model_combo = QComboBox()
        for profile in self.configs.model_profiles.values():
            self.model_combo.addItem(profile.display_name, profile.id)
        self.model_combo.currentIndexChanged.connect(self.on_model_changed)
        header.addWidget(self.model_combo)
        header.addWidget(QLabel("生成预设"))
        self.generation_combo = QComboBox()
        for preset in self.configs.generation_presets["anima_turbo_v1"].values():
            self.generation_combo.addItem(preset.display_name, preset.id)
        self.generation_combo.currentIndexChanged.connect(self.on_generation_preset_changed)
        header.addWidget(self.generation_combo)
        header.addWidget(QLabel("质量预设"))
        self.quality_combo = QComboBox()
        for profile in self.configs.quality_profiles.values():
            self.quality_combo.addItem(profile.display_name, profile.id)
        self.quality_combo.currentIndexChanged.connect(self.recompile_from_ui)
        header.addWidget(self.quality_combo)
        header.addStretch()
        self.lock_english = QCheckBox("锁定英文")
        header.addWidget(self.lock_english)
        translate_button = QPushButton("翻译并编译")
        translate_button.setDefault(True)
        translate_button.clicked.connect(self.translate_and_compile)
        header.addWidget(translate_button)
        save_button = QPushButton("保存")
        save_button.clicked.connect(self.save_job)
        header.addWidget(save_button)
        root_layout.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([400, 570, 500])
        root_layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        for text, slot in (
            ("复制正向", lambda: self.copy_compiled_prompt("positive")),
            ("复制负向", lambda: self.copy_compiled_prompt("negative")),
            ("复制全部参数", self.copy_all), ("导出任务 JSON", self.export_json),
            ("收藏并保存", lambda: self.save_job(True)), ("历史记录", self.open_history),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            footer.addWidget(button)
        footer.addStretch()
        root_layout.addLayout(footer)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        group = QGroupBox("中文输入")
        gl = QVBoxLayout(group)
        self.chinese = QTextEdit()
        self.chinese.setPlaceholderText("例如：一个白发金瞳的女孩坐在桌边，双腿垂下，清晨阳光从窗户照进来。")
        gl.addWidget(self.chinese)
        layout.addWidget(group, 3)

        composition = QGroupBox("人数与构图")
        grid = QGridLayout(composition)
        self.people_count = QSpinBox(); self.people_count.setRange(0, 20); self.people_count.valueChanged.connect(self.on_people_count_changed)
        self.shot = self._combo(["头像", "胸像", "半身", "膝上", "全身", "远景"])
        self.camera = self._combo(["平视", "高机位", "低机位"])
        self.angle = self._combo(["无", "正面", "侧面", "背面", "三分之四"])
        self.gaze = self._combo(["无", "看镜头", "看人物", "看物体", "看向画外"])
        self.aspect = self._combo(["方形", "竖图", "横图"])
        self.position = self._combo(["无", "左", "中", "右"])
        self.composition_mode = QComboBox()
        self.composition_mode.addItem("智能推荐", "smart"); self.composition_mode.addItem("混合模式", "mixed"); self.composition_mode.addItem("手动模式", "manual")
        self.subject_mode = QComboBox()
        self.subject_mode.addItem("自动识别", SubjectMode.AUTO.value)
        self.subject_mode.addItem("人物", SubjectMode.CHARACTER.value)
        self.subject_mode.addItem("纯场景", SubjectMode.SCENE.value)
        self.subject_mode.addItem("人物与场景", SubjectMode.MIXED.value)
        self.subject_mode.currentIndexChanged.connect(self.on_subject_mode_changed)
        self.composition_mode.currentIndexChanged.connect(self.on_composition_mode_changed)
        grid.addWidget(QLabel("模式"), 0, 0); grid.addWidget(self.composition_mode, 0, 1, 1, 2)
        self.composition_preset = QComboBox()
        self.composition_preset.addItem("智能推荐", "smart")
        for preset in self.configs.composition_presets.values():
            self.composition_preset.addItem(preset.display_name, preset.id)
        apply_composition_preset = QPushButton("应用预设")
        apply_composition_preset.clicked.connect(self.apply_composition_preset)
        grid.addWidget(QLabel("构图预设"), 1, 0); grid.addWidget(self.composition_preset, 1, 1); grid.addWidget(apply_composition_preset, 1, 2)
        grid.addWidget(QLabel("主体类型"), 2, 0); grid.addWidget(self.subject_mode, 2, 1, 1, 2)
        grid.addWidget(QLabel("人数"), 3, 0); grid.addWidget(self.people_count, 3, 1)
        self.composition_controls = {
            "shot": self.shot, "camera_height": self.camera, "angle": self.angle,
            "gaze": self.gaze, "aspect": self.aspect, "subject_position": self.position,
        }
        labels = {"shot":"景别", "camera_height":"机位", "angle":"角度", "gaze":"视线", "aspect":"画幅", "subject_position":"主体"}
        self.composition_state_boxes: dict[str, QComboBox] = {}
        self.composition_reason_labels: dict[str, QLabel] = {}
        for row, (field_name, widget) in enumerate(self.composition_controls.items(), 4):
            state = QComboBox(); state.addItem("自动", CompositionFieldState.AUTO.value); state.addItem("手动", CompositionFieldState.USER_SELECTED.value); state.addItem("锁定", CompositionFieldState.LOCKED.value)
            reason = QLabel(); reason.setWordWrap(True); reason.setStyleSheet("color: #777; font-size: 11px")
            self.composition_state_boxes[field_name] = state; self.composition_reason_labels[field_name] = reason
            grid.addWidget(QLabel(labels[field_name]), row, 0); grid.addWidget(widget, row, 1); grid.addWidget(state, row, 2); grid.addWidget(reason, row, 3)
            widget.currentIndexChanged.connect(lambda _=0, name=field_name: self.on_composition_value_changed(name))
            state.currentIndexChanged.connect(lambda _=0, name=field_name: self.on_composition_state_changed(name))
        recommend = QPushButton("重新推荐构图"); recommend.clicked.connect(self.recommend_composition)
        grid.addWidget(recommend, 10, 1, 1, 2)
        grid.setColumnStretch(3, 1)
        layout.addWidget(composition)

        slots = QGroupBox("角色槽位（属性不会混入公共区）")
        sl = QVBoxLayout(slots)
        self.slot_table = QTableWidget(1, 7)
        self.slot_table.setHorizontalHeaderLabels(["位置", "名称", "性别", "身份标签", "外观标签", "服装标签", "动作/关系英文"])
        self.slot_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.slot_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.slot_table.setMinimumHeight(175)
        self.slot_table.itemChanged.connect(self.on_slot_item_changed)
        sl.addWidget(self.slot_table)
        card_buttons = QHBoxLayout()
        manage_cards = QPushButton("打开角色卡库"); manage_cards.clicked.connect(lambda: self.open_entity_library(CharacterCard))
        card_buttons.addWidget(manage_cards); card_buttons.addStretch(); sl.addLayout(card_buttons)
        layout.addWidget(slots, 2)
        return panel

    def _build_center_panel(self) -> QWidget:
        tabs = QTabWidget()
        translation = QWidget(); tl = QVBoxLayout(translation)
        tl.addWidget(QLabel("英文翻译（可编辑；编辑后点“按英文重新编译”）"))
        self.english = QTextEdit(); tl.addWidget(self.english, 2)
        edit_button = QPushButton("按英文重新回译并编译"); edit_button.clicked.connect(self.compile_edited_english); tl.addWidget(edit_button)
        tl.addWidget(QLabel("回译中文（仅供检查）"))
        self.back_chinese = QTextEdit(); self.back_chinese.setReadOnly(True); tl.addWidget(self.back_chinese, 2)
        tl.addWidget(QLabel("关键差异检查"))
        self.warning_list = QListWidget(); self.warning_list.setMaximumHeight(100); tl.addWidget(self.warning_list)
        tabs.addTab(translation, "翻译与回译")

        tags = QWidget(); tag_layout = QVBoxLayout(tags)
        tag_layout.addWidget(QLabel("取消勾选会将自动标签加入排除列表，重新编译也不会回来。"))
        self.tag_table = QTableWidget(0, 4)
        self.tag_table.setHorizontalHeaderLabels(["使用", "标签", "类别", "来源"])
        self.tag_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tag_table.itemChanged.connect(self.on_tag_changed)
        tag_layout.addWidget(self.tag_table)
        add_row = QHBoxLayout(); self.add_tag_edit = QLineEdit(); self.add_tag_edit.setPlaceholderText("手动添加并锁定标签")
        add_tag = QPushButton("添加锁定标签"); add_tag.clicked.connect(self.add_locked_tag)
        add_row.addWidget(self.add_tag_edit); add_row.addWidget(add_tag); tag_layout.addLayout(add_row)
        search_row = QHBoxLayout(); self.tag_search_edit = QLineEdit(); self.tag_search_edit.setPlaceholderText("搜索 5.5 万条本地标签/别名")
        search_button = QPushButton("搜索标签库"); search_button.clicked.connect(self.search_tag_database)
        search_row.addWidget(self.tag_search_edit); search_row.addWidget(search_button); tag_layout.addLayout(search_row)
        self.tag_search_results = QListWidget(); self.tag_search_results.setMaximumHeight(130); self.tag_search_results.itemDoubleClicked.connect(self.add_search_result)
        tag_layout.addWidget(self.tag_search_results)
        tabs.addTab(tags, "标签")

        enhancements = QWidget(); el = QVBoxLayout(enhancements)
        el.addWidget(QLabel("程序增强内容可关闭、可编辑；锁定后即使来源文本改变也会保留。"))
        self.enhancement_table = QTableWidget(0, 5)
        self.enhancement_table.setHorizontalHeaderLabels(["启用", "类型", "来源规则", "英文内容", "锁定"])
        self.enhancement_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        el.addWidget(self.enhancement_table)
        apply_enh = QPushButton("应用增强修改"); apply_enh.clicked.connect(self.apply_enhancement_changes); el.addWidget(apply_enh)
        tabs.addTab(enhancements, "增强内容")
        return tabs

    def _build_right_panel(self) -> QWidget:
        panel = QWidget(); layout = QVBoxLayout(panel)
        style = QGroupBox("画师与 LoRA")
        form = QFormLayout(style)
        self.artists = QLineEdit(); self.artists.setPlaceholderText("例如：rurudo, artist name（逗号分隔）")
        self.loras = QLineEdit(); self.loras.setPlaceholderText("例如：my_lora:0.8:trigger word")
        form.addRow("画师串", self.artists); form.addRow("LoRA", self.loras)
        apply_style = QPushButton("应用"); apply_style.clicked.connect(self.recompile_from_ui); form.addRow(apply_style)
        libraries = QHBoxLayout()
        artist_lib = QPushButton("画师库"); artist_lib.clicked.connect(lambda: self.open_entity_library(ArtistProfile))
        lora_lib = QPushButton("LoRA 库"); lora_lib.clicked.connect(lambda: self.open_entity_library(LoRAProfile))
        libraries.addWidget(artist_lib); libraries.addWidget(lora_lib); form.addRow(libraries)
        layout.addWidget(style)

        params = QGroupBox("模型参数（自动 / 手动 / 锁定）")
        grid = QGridLayout(params)
        self.width = QSpinBox(); self.width.setRange(256, 4096); self.width.setSingleStep(64)
        self.height = QSpinBox(); self.height.setRange(256, 4096); self.height.setSingleStep(64)
        self.steps = QSpinBox(); self.steps.setRange(1, 200)
        self.cfg = QDoubleSpinBox(); self.cfg.setRange(0, 30); self.cfg.setDecimals(2); self.cfg.setSingleStep(.5)
        self.sampler = QLineEdit(); self.scheduler = QLineEdit(); self.seed = QLineEdit("-1")
        self.batch = QSpinBox(); self.batch.setRange(1, 32)
        self.parameter_controls = {
            "width": self.width, "height": self.height, "steps": self.steps,
            "cfg": self.cfg, "sampler": self.sampler, "scheduler": self.scheduler,
        }
        self.parameter_state_boxes: dict[str, QComboBox] = {}
        labels = {"width":"宽", "height":"高", "steps":"步数", "cfg":"CFG", "sampler":"采样器", "scheduler":"调度器"}
        for row, (field_name, widget) in enumerate(self.parameter_controls.items()):
            state = QComboBox()
            state.addItem("自动", GenerationFieldState.AUTO.value)
            state.addItem("手动", GenerationFieldState.USER_SELECTED.value)
            state.addItem("锁定", GenerationFieldState.LOCKED.value)
            self.parameter_state_boxes[field_name] = state
            grid.addWidget(QLabel(labels[field_name]), row, 0); grid.addWidget(widget, row, 1); grid.addWidget(state, row, 2)
            state.currentIndexChanged.connect(lambda _=0, name=field_name: self.on_generation_state_changed(name))
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(lambda _=0, name=field_name: self.on_generation_value_changed(name))
            else:
                widget.editingFinished.connect(lambda name=field_name: self.on_generation_value_changed(name))
        grid.addWidget(QLabel("Seed"), 6, 0); grid.addWidget(self.seed, 6, 1)
        grid.addWidget(QLabel("批量"), 7, 0); grid.addWidget(self.batch, 7, 1)
        layout.addWidget(params)

        layout.addWidget(QLabel("Positive Prompt"))
        self.positive = QTextEdit(); self.positive.setReadOnly(True); layout.addWidget(self.positive, 4)
        layout.addWidget(QLabel("Negative Prompt"))
        self.negative = QTextEdit(); self.negative.setReadOnly(True); self.negative.setMaximumHeight(110); layout.addWidget(self.negative)
        self.model_note = QLabel(); self.model_note.setWordWrap(True); self.model_note.setStyleSheet("color: #777")
        layout.addWidget(self.model_note)
        return panel

    @staticmethod
    def _combo(values: list[str]) -> QComboBox:
        box = QComboBox(); box.addItems(values); return box

    def _resize_slots(self, count: int) -> None:
        rows = min(count, 3) if count >= 4 else count
        self.slot_table.setRowCount(rows)
        positions = ["left", "center", "right"] if count == 3 else (["left", "right"] if count == 2 else ["center"])
        for row in range(rows):
            if not self.slot_table.item(row, 0):
                self.slot_table.setItem(row, 0, QTableWidgetItem(positions[row] if row < len(positions) else f"subject {row + 1}"))
            for col in range(1, 7):
                if not self.slot_table.item(row, col):
                    self.slot_table.setItem(row, col, QTableWidgetItem("1girl" if col == 2 else ""))
        if count >= 4:
            self.statusBar().showMessage("群像模式：仅精确描述前三个核心角色，不保证所有人物特征稳定。", 8000)

    def _sync_ui_to_job(self) -> None:
        preserve_hidden_slots = self.job.effective_subject_mode() == SubjectMode.SCENE and self.slot_table.rowCount() == 0
        self.job.project_name = self.project_name.text().strip() or "未命名项目"
        self.job.original_zh = self.chinese.toPlainText()
        self.job.quality_profile_id = self.quality_combo.currentData()
        self.job.subject_mode = SubjectMode(self.subject_mode.currentData() or SubjectMode.AUTO.value)
        comp = self.job.composition
        comp.mode = self.composition_mode.currentData() or "mixed"
        comp.people_count = self.people_count.value(); comp.shot = self.shot.currentText(); comp.camera_height = self.camera.currentText()
        comp.angle = self.angle.currentText(); comp.gaze = self.gaze.currentText(); comp.aspect = self.aspect.currentText(); comp.subject_position = self.position.currentText()
        for field_name, state_box in self.composition_state_boxes.items():
            comp.decision(field_name).state = CompositionFieldState(state_box.currentData())
        if not preserve_hidden_slots:
            slots: list[CharacterSlot] = []
            for row in range(self.slot_table.rowCount()):
                values = [(self.slot_table.item(row, col).text().strip() if self.slot_table.item(row, col) else "") for col in range(7)]
                slots.append(CharacterSlot(position=values[0], display_name=values[1], gender_tag=values[2] or "1girl",
                    identity_tags=self._split(values[3]), appearance_tags=self._split(values[4]), clothing_tags=self._split(values[5]),
                    action_text=values[6], locked=True))
            self.job.character_slots = slots
        ui_artists = self._split(self.artists.text())
        self.job.artist_selection_sources = {
            artist: self.job.artist_selection_sources.get(artist, "manual")
            for artist in ui_artists
        }
        self.job.artist_selection = ui_artists
        parsed_loras = self._parse_loras(self.loras.text())
        old_loras = {item.logical_id.casefold(): item for item in self.job.lora_selection}
        reconciled_loras: list[LoRASelection] = []
        for item in parsed_loras:
            old = old_loras.get(item.logical_id.casefold())
            if old and old.weight == item.weight and old.trigger_words == item.trigger_words:
                reconciled_loras.append(old.model_copy(deep=True))
            else:
                if old and old.file_name:
                    item.file_name = old.file_name
                item.source = "manual"
                reconciled_loras.append(item)
        self.job.lora_selection = reconciled_loras
        p = self.job.generation_params
        ui_values = {
            "width": self.width.value(), "height": self.height.value(), "steps": self.steps.value(),
            "cfg": self.cfg.value(), "sampler": self.sampler.text().strip() or "euler",
            "scheduler": self.scheduler.text().strip() or "normal",
        }
        if not self._updating:
            for field_name, value in ui_values.items():
                if value != getattr(p, field_name) and p.state(field_name) == GenerationFieldState.AUTO:
                    p.set_state(field_name, GenerationFieldState.USER_SELECTED)
        for field_name, value in ui_values.items():
            setattr(p, field_name, value)
        try: p.seed = int(self.seed.text())
        except ValueError: p.seed = -1
        p.batch_size = self.batch.value()

    @staticmethod
    def _split(text: str) -> list[str]:
        return [x.strip() for x in text.replace("，", ",").split(",") if x.strip()]

    @classmethod
    def _parse_loras(cls, text: str) -> list[LoRASelection]:
        result = []
        for raw in cls._split(text):
            parts = raw.split(":", 2)
            try: weight = float(parts[1]) if len(parts) > 1 else .8
            except ValueError: weight = .8
            triggers = [x.strip() for x in parts[2].split("+")] if len(parts) > 2 else []
            result.append(LoRASelection(logical_id=parts[0], file_name=parts[0], weight=weight, trigger_words=triggers))
        return result

    def _load_job_into_ui(self) -> None:
        self._updating = True
        j = self.job
        self.project_name.setText(j.project_name); self.chinese.setPlainText(j.original_zh); self.english.setPlainText(j.translated_en)
        self.back_chinese.setPlainText(j.back_translated_zh); self.lock_english.setChecked(j.translation_state == ItemState.LOCKED)
        self._set_combo_data(self.model_combo, j.model_profile_id); self._set_combo_data(self.generation_combo, j.generation_preset_id); self._set_combo_data(self.quality_combo, j.quality_profile_id)
        c = j.composition; self.people_count.setValue(c.people_count)
        self._set_combo_data(self.subject_mode, j.subject_mode.value)
        self._set_combo_data(self.composition_mode, c.mode)
        for combo, value in ((self.shot,c.shot),(self.camera,c.camera_height),(self.angle,c.angle),(self.gaze,c.gaze),(self.aspect,c.aspect),(self.position,c.subject_position)):
            combo.setCurrentText(value)
        for field_name, state_box in self.composition_state_boxes.items():
            decision = c.decision(field_name)
            self._set_combo_data(state_box, decision.state.value)
            self.composition_controls[field_name].setEnabled(decision.state != CompositionFieldState.LOCKED)
            self.composition_reason_labels[field_name].setText(decision.reason or "")
        self._resize_slots(c.people_count)
        for row, slot in enumerate(j.character_slots[:self.slot_table.rowCount()]):
            vals = [slot.position, slot.display_name, slot.gender_tag, ", ".join(slot.identity_tags), ", ".join(slot.appearance_tags), ", ".join(slot.clothing_tags), slot.action_text]
            for col, value in enumerate(vals): self.slot_table.setItem(row, col, QTableWidgetItem(value))
        self.artists.setText(", ".join(j.artist_selection))
        self.loras.setText(", ".join(f"{x.logical_id}:{x.weight}" + ((":" + "+".join(x.trigger_words)) if x.trigger_words else "") for x in j.lora_selection))
        p=j.generation_params; self.width.setValue(p.width); self.height.setValue(p.height); self.steps.setValue(p.steps); self.cfg.setValue(p.cfg)
        self.sampler.setText(p.sampler); self.scheduler.setText(p.scheduler); self.seed.setText(str(p.seed)); self.batch.setValue(p.batch_size)
        for field_name, state_box in self.parameter_state_boxes.items():
            state = p.state(field_name)
            self._set_combo_data(state_box, state.value)
            self.parameter_controls[field_name].setEnabled(state != GenerationFieldState.LOCKED)
        self._refresh_results()
        self._updating = False

    @staticmethod
    def _set_combo_data(combo: QComboBox, data: str) -> None:
        index = combo.findData(data)
        if index >= 0: combo.setCurrentIndex(index)

    def _refresh_results(self) -> None:
        j = self.job
        previous_updating = self._updating
        self._updating = True
        self.english.setPlainText(j.translated_en); self.back_chinese.setPlainText(j.back_translated_zh)
        self.positive.setPlainText(j.positive_prompt); self.negative.setPlainText(j.negative_prompt)
        c = j.composition
        if c.people_count > 0:
            self._cached_character_people_count = c.people_count
        elif self.people_count.value() > 0:
            self._cached_character_people_count = self.people_count.value()
        self.people_count.setValue(c.people_count)
        self._set_combo_data(self.subject_mode, j.subject_mode.value)
        self._resize_slots(c.people_count)
        for row, slot in enumerate(j.character_slots[:self.slot_table.rowCount()]):
            values = [
                slot.position, slot.display_name, slot.gender_tag, ", ".join(slot.identity_tags),
                ", ".join(slot.appearance_tags), ", ".join(slot.clothing_tags), slot.action_text,
            ]
            for col, value in enumerate(values):
                self.slot_table.setItem(row, col, QTableWidgetItem(value))
        self.artists.setText(", ".join(j.artist_selection))
        self.loras.setText(", ".join(
            f"{x.logical_id}:{x.weight}" + ((":" + "+".join(x.trigger_words)) if x.trigger_words else "")
            for x in j.lora_selection
        ))
        for field_name, combo in self.composition_controls.items():
            combo.setCurrentText(getattr(c, field_name))
            decision = c.decision(field_name)
            self._set_combo_data(self.composition_state_boxes[field_name], decision.state.value)
            combo.setEnabled(decision.state != CompositionFieldState.LOCKED)
            self.composition_reason_labels[field_name].setText(decision.reason or "")
        self._set_combo_data(self.generation_combo, j.generation_preset_id)
        p = j.generation_params
        self.width.setValue(p.width); self.height.setValue(p.height); self.steps.setValue(p.steps); self.cfg.setValue(p.cfg)
        self.sampler.setText(p.sampler); self.scheduler.setText(p.scheduler)
        for field_name, state_box in self.parameter_state_boxes.items():
            state = p.state(field_name)
            self._set_combo_data(state_box, state.value)
            self.parameter_controls[field_name].setEnabled(state != GenerationFieldState.LOCKED)
        self.warning_list.clear()
        for warning in j.semantic_warnings:
            item = QListWidgetItem(f"[{warning.level.value.upper()}] {warning.message}")
            item.setForeground({"green": QColor("#288a48"), "yellow": QColor("#b07800"), "red": QColor("#c0392b")}[warning.level.value])
            self.warning_list.addItem(item)
        self.tag_table.setRowCount(len(j.matched_tags))
        source_names = {"direct":"直接匹配","synonym":"同义词匹配","character_card":"角色卡","artist":"画师库","parameter":"参数补充","derived":"规则推导","user_added":"用户添加"}
        for row, tag in enumerate(j.matched_tags):
            check = QTableWidgetItem(); check.setFlags(check.flags() | Qt.ItemIsUserCheckable); check.setCheckState(Qt.Unchecked if tag.tag in j.excluded_tags else Qt.Checked)
            check.setData(Qt.UserRole, tag.tag); self.tag_table.setItem(row, 0, check)
            self.tag_table.setItem(row, 1, QTableWidgetItem(tag.tag)); self.tag_table.setItem(row, 2, QTableWidgetItem(tag.category))
            self.tag_table.setItem(row, 3, QTableWidgetItem(source_names.get(tag.source_type, tag.source_type)))
        self.enhancement_table.setRowCount(len(j.enhancements))
        for row, enh in enumerate(j.enhancements):
            check = QTableWidgetItem(); check.setFlags(check.flags() | Qt.ItemIsUserCheckable); check.setCheckState(Qt.Checked if enh.enabled else Qt.Unchecked); check.setData(Qt.UserRole, enh.id)
            lock = QTableWidgetItem(); lock.setFlags(lock.flags() | Qt.ItemIsUserCheckable); lock.setCheckState(Qt.Checked if enh.state == ItemState.LOCKED else Qt.Unchecked)
            self.enhancement_table.setItem(row, 0, check); self.enhancement_table.setItem(row, 1, QTableWidgetItem(enh.type)); self.enhancement_table.setItem(row, 2, QTableWidgetItem(enh.source_rule)); self.enhancement_table.setItem(row, 3, QTableWidgetItem(enh.content)); self.enhancement_table.setItem(row, 4, lock)
        profile = self.configs.get_model(j.model_profile_id)
        preset = self.configs.get_generation_preset(j.model_profile_id, j.generation_preset_id)
        self.model_note.setText(f"{profile.display_name} · {profile.status} · {profile.notes}\n生成预设：{preset.display_name} · {preset.notes}")
        self._updating = previous_updating

    def translate_and_compile(self) -> None:
        try:
            self.statusBar().showMessage(f"正在使用{self.pipeline.translation.engine_name}翻译，首次加载可能需要约 20 秒…")
            QApplication.processEvents()
            self._sync_ui_to_job()
            lora_profiles = self.repository.list_entities(LoRAProfile)
            self.pipeline.set_lora_profiles(lora_profiles)
            known_entities = []
            for profile in lora_profiles:
                known_entities.extend((value, "lora") for value in {
                    profile.id, profile.display_name, Path(profile.file_name).stem,
                } if value)
            self.job.translation_state = ItemState.LOCKED if self.lock_english.isChecked() and self.job.translated_en else ItemState.AUTO
            self.pipeline.translate(self.job, known_entities)
            self._refresh_results()
            self.statusBar().showMessage("翻译、回译、匹配和编译已完成。", 5000)
        except Exception as exc: self._show_error("处理失败", exc)

    def compile_edited_english(self) -> None:
        try:
            self._sync_ui_to_job(); self.pipeline.update_english(self.job, self.english.toPlainText())
            if self.lock_english.isChecked(): self.job.translation_state = ItemState.LOCKED
            self._refresh_results()
        except Exception as exc: self._show_error("重新编译失败", exc)

    def recompile_from_ui(self) -> None:
        if self._updating: return
        try:
            self._sync_and_recompile(); self._refresh_results()
        except Exception as exc: self._show_error("编译失败", exc)

    def _sync_and_recompile(self) -> None:
        self._sync_ui_to_job()
        people_override = None if self.job.effective_subject_mode() == SubjectMode.SCENE else self.job.composition.people_count
        self.pipeline.recompile(self.job, people_count_override=people_override)

    def on_people_count_changed(self, count: int) -> None:
        if self._updating:
            self._resize_slots(count)
            return
        if count <= 0 and self.job.effective_subject_mode() != SubjectMode.SCENE:
            previous = self._updating; self._updating = True
            self.people_count.setValue(1); self._resize_slots(1)
            self._updating = previous
        else:
            if count > 0:
                self._cached_character_people_count = count
            previous = self._updating; self._updating = True
            self._resize_slots(count)
            self._updating = previous
        self.recompile_from_ui()

    def on_subject_mode_changed(self) -> None:
        if self._updating:
            return
        old_scene = self.job.effective_subject_mode() == SubjectMode.SCENE
        new_mode = SubjectMode(self.subject_mode.currentData() or SubjectMode.AUTO.value)
        if not old_scene and self.people_count.value() > 0:
            self._cached_character_people_count = self.people_count.value()
        if old_scene and new_mode in (SubjectMode.CHARACTER, SubjectMode.MIXED):
            previous = self._updating; self._updating = True
            self.people_count.setValue(max(1, self._cached_character_people_count))
            self._resize_slots(self.people_count.value())
            for row, slot in enumerate(self.job.character_slots[:self.slot_table.rowCount()]):
                values = [
                    slot.position, slot.display_name, slot.gender_tag, ", ".join(slot.identity_tags),
                    ", ".join(slot.appearance_tags), ", ".join(slot.clothing_tags), slot.action_text,
                ]
                for col, value in enumerate(values):
                    self.slot_table.setItem(row, col, QTableWidgetItem(value))
            self._updating = previous
        self.recompile_from_ui()

    def on_slot_item_changed(self) -> None:
        if not self._updating:
            self.recompile_from_ui()

    def on_composition_value_changed(self, field_name: str) -> None:
        if self._updating:
            return
        decision = self.job.composition.decision(field_name)
        if decision.state != CompositionFieldState.LOCKED:
            decision.state = CompositionFieldState.USER_SELECTED
            previous = self._updating; self._updating = True
            self._set_combo_data(self.composition_state_boxes[field_name], CompositionFieldState.USER_SELECTED.value)
            self._updating = previous
        self.recompile_from_ui()

    def on_composition_state_changed(self, field_name: str) -> None:
        if self._updating:
            return
        state = CompositionFieldState(self.composition_state_boxes[field_name].currentData())
        self.job.composition.decision(field_name).state = state
        self.composition_controls[field_name].setEnabled(state != CompositionFieldState.LOCKED)
        self._sync_ui_to_job()
        if state == CompositionFieldState.AUTO:
            self.pipeline.recommend_composition(self.job)
        else:
            self.pipeline.compiler.compile(self.job)
        self._refresh_results()

    def on_composition_mode_changed(self) -> None:
        if self._updating:
            return
        mode = self.composition_mode.currentData() or "mixed"
        self.job.composition.mode = mode
        previous = self._updating; self._updating = True
        if mode == "smart":
            for field_name, state_box in self.composition_state_boxes.items():
                decision = self.job.composition.decision(field_name)
                if decision.state != CompositionFieldState.LOCKED:
                    decision.state = CompositionFieldState.AUTO
                    self._set_combo_data(state_box, CompositionFieldState.AUTO.value)
        elif mode == "manual":
            for field_name, state_box in self.composition_state_boxes.items():
                decision = self.job.composition.decision(field_name)
                if decision.state == CompositionFieldState.AUTO:
                    decision.state = CompositionFieldState.USER_SELECTED
                    self._set_combo_data(state_box, CompositionFieldState.USER_SELECTED.value)
        self._updating = previous
        self.recommend_composition()

    def recommend_composition(self) -> None:
        if self._updating:
            return
        try:
            self._sync_ui_to_job(); self.pipeline.recommend_composition(self.job); self._refresh_results()
            self.statusBar().showMessage("构图推荐已更新；手动和锁定项保持不变。", 5000)
        except Exception as exc: self._show_error("构图推荐失败", exc)

    def apply_composition_preset(self) -> None:
        if self._updating:
            return
        preset_id = self.composition_preset.currentData()
        if preset_id == "smart":
            previous = self._updating; self._updating = True
            for field_name, state_box in self.composition_state_boxes.items():
                if self.job.composition.decision(field_name).state != CompositionFieldState.LOCKED:
                    self.job.composition.decision(field_name).state = CompositionFieldState.AUTO
                    self._set_combo_data(state_box, CompositionFieldState.AUTO.value)
            self._updating = previous
            self.recommend_composition()
            return
        try:
            self._sync_ui_to_job()
            self.pipeline.apply_composition_preset(self.job, preset_id)
            self._load_job_into_ui()
            self.statusBar().showMessage("构图预设已应用；锁定构图项保持不变。", 5000)
        except Exception as exc:
            self._show_error("构图预设应用失败", exc)

    def on_model_changed(self) -> None:
        if self._updating: return
        try:
            self._sync_ui_to_job()
            reset_fields = [
                name for name in ("steps", "cfg", "sampler", "scheduler")
                if self.job.generation_params.state(name) == GenerationFieldState.USER_SELECTED
            ]
            self.pipeline.switch_model(self.job, self.model_combo.currentData()); self._load_job_into_ui()
            suffix = f" 手动参数 {', '.join(reset_fields)} 已恢复为新模型的自动值。" if reset_fields else ""
            self.statusBar().showMessage(f"模型已切换；质量词和推荐参数已重新编译。{suffix}", 7000)
        except Exception as exc: self._show_error("模型切换失败", exc)

    def on_generation_preset_changed(self) -> None:
        if self._updating:
            return
        try:
            self._sync_ui_to_job()
            self.pipeline.apply_generation_preset(self.job, self.generation_combo.currentData())
            self._load_job_into_ui()
            self.statusBar().showMessage("生成预设已应用；锁定参数保持不变。", 5000)
        except Exception as exc:
            self._show_error("生成预设应用失败", exc)

    def on_generation_value_changed(self, field_name: str) -> None:
        if self._updating:
            return
        params = self.job.generation_params
        if params.state(field_name) != GenerationFieldState.LOCKED:
            params.set_state(field_name, GenerationFieldState.USER_SELECTED)
            previous = self._updating; self._updating = True
            self._set_combo_data(self.parameter_state_boxes[field_name], GenerationFieldState.USER_SELECTED.value)
            self._updating = previous
        self._sync_ui_to_job()

    def on_generation_state_changed(self, field_name: str) -> None:
        if self._updating:
            return
        state = GenerationFieldState(self.parameter_state_boxes[field_name].currentData())
        self.job.generation_params.set_state(field_name, state)
        self.parameter_controls[field_name].setEnabled(state != GenerationFieldState.LOCKED)
        self._sync_ui_to_job()
        if state == GenerationFieldState.AUTO:
            self.pipeline.compiler.apply_model_defaults(self.job)
            self.pipeline.composition_recommender.apply_aspect_dimensions(self.job)
        self._refresh_results()

    def on_tag_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.column() != 0: return
        tag = item.data(Qt.UserRole)
        if not tag: return
        if item.checkState() == Qt.Unchecked:
            if tag not in self.job.excluded_tags: self.job.excluded_tags.append(tag)
            if tag in self.job.locked_tags: self.job.locked_tags.remove(tag)
        elif tag in self.job.excluded_tags: self.job.excluded_tags.remove(tag)
        self._sync_and_recompile(); self._refresh_results()

    def add_locked_tag(self) -> None:
        tag = self.add_tag_edit.text().strip().replace("_", " ")
        if tag and tag not in self.job.locked_tags:
            self.job.locked_tags.append(tag)
            if tag in self.job.excluded_tags: self.job.excluded_tags.remove(tag)
            self._sync_and_recompile(); self._refresh_results(); self.add_tag_edit.clear()

    def search_tag_database(self) -> None:
        self.tag_search_results.clear()
        for entry in self.pipeline.matcher.database.search(self.tag_search_edit.text(), 50):
            item = QListWidgetItem(f"{entry['output_name']}  ·  {entry['post_count']:,} posts")
            item.setData(Qt.UserRole, entry["output_name"]); self.tag_search_results.addItem(item)
        if self.tag_search_results.count() == 0:
            self.tag_search_results.addItem("没有匹配结果，或本地标签资源尚未安装。")

    def add_search_result(self, item: QListWidgetItem) -> None:
        tag = item.data(Qt.UserRole)
        if not tag: return
        self.add_tag_edit.setText(tag); self.add_locked_tag()

    def apply_enhancement_changes(self) -> None:
        by_id = {x.id: x for x in self.job.enhancements}
        for row in range(self.enhancement_table.rowCount()):
            id_ = self.enhancement_table.item(row,0).data(Qt.UserRole)
            if id_ in by_id:
                enhancement = by_id[id_]
                enhancement.enabled = self.enhancement_table.item(row,0).checkState() == Qt.Checked
                edited_content = self.enhancement_table.item(row,3).text().strip()
                is_locked = self.enhancement_table.item(row,4).checkState() == Qt.Checked
                if is_locked:
                    enhancement.state = ItemState.LOCKED
                elif edited_content != enhancement.content:
                    enhancement.state = ItemState.USER_EDITED
                elif enhancement.state == ItemState.LOCKED:
                    enhancement.state = ItemState.AUTO
                enhancement.content = edited_content
        self._sync_and_recompile(); self._refresh_results()

    def save_job(self, favorite: bool = False) -> None:
        try:
            self._sync_and_recompile(); self._refresh_results()
            self.repository.save_job(self.job, bool(favorite)); self.statusBar().showMessage("任务已保存到本地历史。", 4000)
        except Exception as exc: self._show_error("保存失败", exc)

    def open_history(self) -> None:
        dialog = HistoryDialog(self.repository, self)
        if dialog.exec() == QDialog.Accepted and dialog.selected_id:
            try: self.job = self.repository.load_job(dialog.selected_id); self._load_job_into_ui()
            except Exception as exc: self._show_error("读取历史失败", exc)

    def new_job(self) -> None:
        self.job = PromptJob(); self.pipeline.compiler.apply_model_defaults(self.job); self._load_job_into_ui()

    def export_json(self) -> None:
        self._sync_and_recompile(); self._refresh_results()
        filename = f"{self.job.project_name or 'anima_task'}.json"
        path, _ = QFileDialog.getSaveFileName(self, "导出任务 JSON", str(Path.home() / filename), "JSON (*.json)")
        if path:
            try: self.exporter.export_task(self.job, Path(path)); self.statusBar().showMessage(f"已导出：{path}", 6000)
            except Exception as exc: self._show_error("导出失败", exc)

    def configure_translation(self) -> None:
        zh_en = QFileDialog.getExistingDirectory(self, "选择本地中译英 Marian 模型目录")
        if not zh_en: return
        en_zh = QFileDialog.getExistingDirectory(self, "选择本地英译中 Marian 模型目录")
        if not en_zh: return
        try:
            engine = LazyLocalMarianEngine(Path(zh_en), Path(en_zh)); self.pipeline.translation = TranslationService(engine)
            self.repository.set_setting("zh_en_model_path", zh_en); self.repository.set_setting("en_zh_model_path", en_zh)
            self.statusBar().showMessage("本地 Marian 翻译模型已加载。", 5000)
        except Exception as exc: self._show_error("模型加载失败", exc)

    def open_tag_browser(self) -> None:
        dialog = TagBrowserDialog(self)
        dialog.exec()

    def open_entity_library(self, initial: type) -> None:
        dialog = EntityLibraryDialog(self.repository, initial, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected_entity: return
        entity = dialog.selected_entity
        if isinstance(entity, CharacterCard):
            row = max(0, self.slot_table.currentRow())
            if row >= self.slot_table.rowCount(): row = 0
            values = [self.slot_table.item(row, col).text() if self.slot_table.item(row, col) else "" for col in range(7)]
            values[1] = entity.display_name; values[2] = entity.gender_tag
            values[3] = ", ".join(entity.identity_tags); values[4] = ", ".join(entity.default_appearance_tags); values[5] = ", ".join(entity.default_clothing_tags)
            for col, value in enumerate(values): self.slot_table.setItem(row, col, QTableWidgetItem(value))
        elif isinstance(entity, ArtistProfile):
            existing = self._split(self.artists.text()); tag = entity.output_tag.lstrip("@")
            if tag not in existing: existing.append(tag)
            self.artists.setText(", ".join(existing))
        elif isinstance(entity, LoRAProfile):
            current = self._split(self.loras.text()); encoded = f"{entity.id}:{entity.default_weight}" + ((":" + "+".join(entity.trigger_words)) if entity.trigger_words else "")
            current.append(encoded); self.loras.setText(", ".join(current))
            self.pipeline.set_lora_profiles(self.repository.list_entities(LoRAProfile))
        self.recompile_from_ui()

    @staticmethod
    def copy_text(text: str) -> None: QApplication.clipboard().setText(text)

    def copy_compiled_prompt(self, kind: str) -> None:
        try:
            self._sync_and_recompile(); self._refresh_results()
            self.copy_text(self.job.positive_prompt if kind == "positive" else self.job.negative_prompt)
        except Exception as exc: self._show_error("复制失败", exc)

    def copy_all(self) -> None:
        try:
            self._sync_and_recompile(); self._refresh_results()
        except Exception as exc:
            self._show_error("复制失败", exc); return
        p=self.job.generation_params
        text=f"Positive:\n{self.job.positive_prompt}\n\nNegative:\n{self.job.negative_prompt}\n\nModel: {self.job.model_profile_id}\nSize: {p.width}x{p.height}\nSteps: {p.steps}\nCFG: {p.cfg}\nSampler: {p.sampler}\nScheduler: {p.scheduler}\nSeed: {p.seed}\nBatch: {p.batch_size}"
        self.copy_text(text)

    def _show_error(self, title: str, exc: Exception) -> None:
        log.exception(title, exc_info=exc); QMessageBox.critical(self, title, str(exc))

    def closeEvent(self, event) -> None:
        self.repository.close(); super().closeEvent(event)
