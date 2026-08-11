from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QInputDialog, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QDoubleSpinBox, QSplitter, QStatusBar, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QToolBar, QVBoxLayout, QWidget,
)

from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteCredentials, RemoteProfile
from anima_prompt_studio.domain.models import (
    ArtistProfile, CharacterCard, CharacterSlot, CompositionFieldState, GenerationFieldState, ItemState,
    LoRAProfile, LoRASelection, PromptJob, SubjectMode,
)
from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio.services.export_service import ExportService
from anima_prompt_studio.services.gallery_server import GalleryServer
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.translation_service import LazyLocalMarianEngine, TranslationService, marian_runtime_available
from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.services.remote.provider_presets import (
    DEFAULT_PROVIDER_PRESET_ID,
    PROVIDER_PRESETS,
    get_provider_preset,
)
from anima_prompt_studio.services.remote.credential_store import CredentialStore, CredentialStoreError
from anima_prompt_studio.services.remote.workflow_discovery import parse_ssh_command
from anima_prompt_studio.services.remote.workflow_compatibility import infer_workflow_model_profiles
from anima_prompt_studio.ui.image_gallery import ImageGalleryWidget
from anima_prompt_studio.ui.library_dialog import EntityLibraryDialog
from anima_prompt_studio.ui.remote_dialogs import (
    RemoteProfileDialog,
    WorkflowProfileDialog,
    build_auto_workflow_profile,
)
from anima_prompt_studio.ui.remote_workers import ConnectionTestWorker, GenerationWorker
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
    def __init__(
        self,
        repository: SQLiteRepository | None = None,
        credential_store: CredentialStore | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository or SQLiteRepository()
        self.credential_store = credential_store or CredentialStore()
        self.configs = ConfigService()
        self.pipeline = PromptPipeline(configs=self.configs, lora_profiles=self.repository.list_entities(LoRAProfile))
        self.exporter = ExportService()
        self.job = PromptJob()
        self._updating = False
        self._cached_character_people_count = 1
        self._remote_threads: list[QThread] = []
        self._remote_workers: list[object] = []
        self._active_generation_worker: GenerationWorker | None = None
        self._direct_remote_id = ""
        self._remote_form_loading = False
        self._last_output_dir = ""
        self._gallery_server: GalleryServer | None = None
        self._responsive_mode = "wide"
        self._responsive_timer = QTimer(self)
        self._responsive_timer.setSingleShot(True)
        self._responsive_timer.timeout.connect(self._apply_responsive_layout)
        self.setWindowTitle("ANIMA 中文提示词辅助工具 V2")
        self.resize(1540, 940)
        self.setMinimumSize(820, 520)
        self._build_ui()
        self._apply_button_styles()
        self._create_menu()
        self._load_configured_translation()
        self.pipeline.compiler.apply_model_defaults(self.job)
        self._load_job_into_ui()
        self.statusBar().showMessage(f"就绪 · 翻译引擎：{self.pipeline.translation.engine_name}")
        QTimer.singleShot(700, self._auto_connect_last_remote)

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
            ("生成图片", self.show_image_gallery, "Ctrl+G"),
        ):
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            file_menu.addAction(action)
        settings = self.menuBar().addMenu("设置")
        model_action = QAction("配置本地 Marian 翻译模型…", self)
        model_action.triggered.connect(self.configure_translation)
        settings.addAction(model_action)
        settings.addSeparator()
        new_remote_action = QAction("新增云主机…", self)
        new_remote_action.triggered.connect(lambda: self.configure_remote_profile(True))
        settings.addAction(new_remote_action)
        edit_remote_action = QAction("编辑当前云主机…", self)
        edit_remote_action.triggered.connect(lambda: self.configure_remote_profile(False))
        settings.addAction(edit_remote_action)
        workflow_action = QAction("导入 ComfyUI API 工作流…", self)
        workflow_action.triggered.connect(self.import_workflow_profile)
        settings.addAction(workflow_action)
        output_action = QAction("设置图片保存目录…", self)
        output_action.triggered.connect(self.configure_output_root)
        settings.addAction(output_action)
        gallery = self.menuBar().addMenu("画廊")
        open_gallery = QAction("打开全部历史图片", self)
        open_gallery.setShortcut("Ctrl+Shift+G")
        open_gallery.triggered.connect(self.open_history_gallery)
        gallery.addAction(open_gallery)
        open_gallery_root = QAction("打开图片保存根目录", self)
        open_gallery_root.triggered.connect(self.open_gallery_root)
        gallery.addAction(open_gallery_root)
        tags_menu = self.menuBar().addMenu("标签")
        browse_tags = QAction("浏览内置标签（灵感库）…", self)
        browse_tags.setShortcut("Ctrl+T")
        browse_tags.triggered.connect(self.open_tag_browser)
        tags_menu.addAction(browse_tags)

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(10, 8, 10, 8)

        header = QVBoxLayout()
        primary_header = QHBoxLayout()
        primary_header.addWidget(QLabel("项目名"))
        self.project_name = QLineEdit("未命名项目")
        self.project_name.setMaximumWidth(260)
        primary_header.addWidget(self.project_name)
        primary_header.addWidget(QLabel("模型"))
        self.model_combo = QComboBox()
        for profile in self.configs.model_profiles.values():
            self.model_combo.addItem(profile.display_name, profile.id)
        self.model_combo.currentIndexChanged.connect(self.on_model_changed)
        primary_header.addWidget(self.model_combo, 1)
        primary_header.addWidget(QLabel("生成预设"))
        self.generation_combo = QComboBox()
        for preset in self.configs.generation_presets["anima_turbo_v1"].values():
            self.generation_combo.addItem(preset.display_name, preset.id)
        self.generation_combo.currentIndexChanged.connect(self.on_generation_preset_changed)
        primary_header.addWidget(self.generation_combo, 1)
        primary_header.addWidget(QLabel("质量预设"))
        self.quality_combo = QComboBox()
        for profile in self.configs.quality_profiles.values():
            self.quality_combo.addItem(profile.display_name, profile.id)
        self.quality_combo.currentIndexChanged.connect(self.recompile_from_ui)
        primary_header.addWidget(self.quality_combo, 1)
        header.addLayout(primary_header)

        action_header = QHBoxLayout()
        action_header.addStretch()
        self.lock_english = QCheckBox("锁定英文")
        action_header.addWidget(self.lock_english)
        self.translate_button = QPushButton("翻译并编译")
        self.translate_button.setProperty("buttonRole", "primary")
        self.translate_button.setDefault(True)
        self.translate_button.clicked.connect(self.translate_and_compile)
        action_header.addWidget(self.translate_button)
        save_button = QPushButton("保存")
        save_button.clicked.connect(self.save_job)
        action_header.addWidget(save_button)
        header.addLayout(action_header)
        root_layout.addLayout(header)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(self._build_left_panel())
        self.main_splitter.addWidget(self._build_center_panel())
        self.main_splitter.addWidget(self._build_right_panel())
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setSizes([400, 570, 500])

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        body_layout.addWidget(self.main_splitter, 1)
        self.remote_panel = self._build_remote_panel()
        body_layout.addWidget(self.remote_panel)
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body_scroll.setWidget(body)
        root_layout.addWidget(self.body_scroll, 1)

        self.footer_toolbar = QToolBar("快捷操作")
        self.footer_toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        for text, slot in (
            ("复制正向", lambda: self.copy_compiled_prompt("positive")),
            ("复制负向", lambda: self.copy_compiled_prompt("negative")),
            ("复制全部参数", self.copy_all), ("导出任务 JSON", self.export_json),
            ("收藏并保存", lambda: self.save_job(True)), ("历史记录", self.open_history),
        ):
            action = self.footer_toolbar.addAction(text)
            action.triggered.connect(slot)
        root_layout.addWidget(self.footer_toolbar)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self._apply_responsive_layout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_responsive_timer"):
            self._responsive_timer.start(80)

    def _apply_responsive_layout(self) -> None:
        if not hasattr(self, "main_splitter"):
            return
        compact = self.size().width() < 1000
        mode = "compact" if compact else "wide"
        if mode == self._responsive_mode and self.main_splitter.orientation() == (
            Qt.Vertical if compact else Qt.Horizontal
        ):
            return
        self._responsive_mode = mode
        self.main_splitter.setOrientation(Qt.Vertical if compact else Qt.Horizontal)
        if compact:
            self.main_splitter.setSizes([360, 520, 430])
            # Let the remote connection row shrink with the window; the body
            # scroll area provides vertical access to the complete form.
            for widget in (
                self.remote_provider_combo,
                self.remote_profile_combo,
                self.workflow_profile_combo,
                self.remote_status,
            ):
                widget.setMinimumWidth(0)
        else:
            self.main_splitter.setSizes([400, 570, 500])
            self.remote_provider_combo.setMinimumWidth(220)
            self.remote_profile_combo.setMinimumWidth(170)
            self.workflow_profile_combo.setMinimumWidth(190)
            self.remote_status.setMinimumWidth(180)

    def _apply_button_styles(self) -> None:
        self.setStyleSheet(self.styleSheet() + """
            QPushButton[buttonRole="primary"] {
                background-color: #2563eb; color: white; border: 1px solid #1d4ed8;
                border-radius: 5px; padding: 5px 13px; font-weight: 600;
            }
            QPushButton[buttonRole="primary"]:hover { background-color: #1d4ed8; }
            QPushButton[buttonRole="success"] {
                background-color: #16803c; color: white; border: 1px solid #126b33;
                border-radius: 5px; padding: 5px 13px; font-weight: 600;
            }
            QPushButton[buttonRole="success"]:hover { background-color: #126b33; }
            QPushButton[buttonRole="danger"] {
                background-color: #b42318; color: white; border: 1px solid #912018;
                border-radius: 5px; padding: 5px 11px; font-weight: 600;
            }
            QPushButton[buttonRole="danger"]:hover { background-color: #912018; }
            QPushButton[buttonRole="primary"]:disabled,
            QPushButton[buttonRole="success"]:disabled,
            QPushButton[buttonRole="danger"]:disabled {
                background-color: #aeb4bd; color: #eef0f3; border-color: #9da3ac;
            }
        """)

    def _build_remote_panel(self) -> QWidget:
        group = QGroupBox("远程生成 · SSH + ComfyUI")
        outer = QVBoxLayout(group)
        connection = QGridLayout()
        connection.addWidget(QLabel("云平台"), 0, 0)
        self.remote_provider_combo = QComboBox(); self.remote_provider_combo.setMinimumWidth(220)
        for preset in PROVIDER_PRESETS:
            self.remote_provider_combo.addItem(preset.display_name, preset.id)
        self.remote_provider_combo.currentIndexChanged.connect(self._apply_remote_provider_preset)
        connection.addWidget(self.remote_provider_combo, 0, 1)
        connection.addWidget(QLabel("已保存"), 0, 2)
        self.remote_profile_combo = QComboBox(); self.remote_profile_combo.setMinimumWidth(170)
        self.remote_profile_combo.currentIndexChanged.connect(self._load_remote_form_from_selection)
        connection.addWidget(self.remote_profile_combo, 0, 3, 1, 2)
        new_button = QPushButton("新连接"); new_button.clicked.connect(self._clear_remote_form)
        connection.addWidget(new_button, 0, 5)
        self.remote_name_edit = QLineEdit(); self.remote_name_edit.setPlaceholderText("例如：东京 4090")

        connection.setColumnStretch(1, 1); connection.setColumnStretch(3, 1)
        outer.addLayout(connection)

        quick = QGridLayout()
        quick.addWidget(QLabel("SSH 登录指令"), 0, 0)
        self.remote_ssh_command_edit = QLineEdit()
        self.remote_ssh_command_edit.setPlaceholderText("在优云智算实例卡片复制 ssh登录指令，然后粘贴到这里")
        quick.addWidget(self.remote_ssh_command_edit, 0, 1)
        parse_button = QPushButton("粘贴并解析")
        parse_button.clicked.connect(self.paste_and_parse_ssh_command)
        quick.addWidget(parse_button, 0, 2)
        quick.addWidget(QLabel("控制台密码"), 1, 0)
        self.remote_password_edit = QLineEdit()
        self.remote_password_edit.setEchoMode(QLineEdit.Password)
        self.remote_password_edit.setPlaceholderText("密码可安全保存到 Windows 凭据管理器")
        quick.addWidget(self.remote_password_edit, 1, 1)
        paste_password = QPushButton("粘贴密码")
        paste_password.clicked.connect(
            lambda: self.remote_password_edit.setText(QApplication.clipboard().text().strip())
        )
        quick.addWidget(paste_password, 1, 2)
        options = QHBoxLayout()
        self.remote_remember_password = QCheckBox("安全记住密码")
        self.remote_remember_password.setChecked(self.credential_store.available)
        self.remote_remember_password.setEnabled(self.credential_store.available)
        self.remote_auto_connect = QCheckBox("启动时自动连接上次云主机")
        self.remote_auto_connect.setChecked(bool(self.repository.get_setting("remote_auto_connect", True)))
        options.addWidget(self.remote_remember_password); options.addWidget(self.remote_auto_connect); options.addStretch()
        quick.addLayout(options, 2, 1, 1, 2)
        self.remote_test_button = QPushButton("一键连接并识别")
        self.remote_test_button.setProperty("buttonRole", "primary")
        self.remote_test_button.clicked.connect(self.connect_remote_quickly)
        self.remote_test_button.setMinimumHeight(34)
        quick.addWidget(self.remote_test_button, 3, 1, 1, 2)
        quick.setColumnStretch(1, 1)
        outer.addLayout(quick)

        self.remote_advanced_button = QPushButton("显示高级连接设置")
        self.remote_advanced_button.setCheckable(True)
        outer.addWidget(self.remote_advanced_button, 0, Qt.AlignLeft)
        self.remote_advanced_panel = QWidget()
        advanced = QGridLayout(self.remote_advanced_panel)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.addWidget(QLabel("连接名称"), 2, 0)
        advanced.addWidget(self.remote_name_edit, 2, 1, 1, 2)
        save_remote_button = QPushButton("仅保存连接")
        save_remote_button.clicked.connect(self.save_remote_connection)
        advanced.addWidget(save_remote_button, 2, 3)
        full_config_button = QPushButton("完整配置对话框…")
        full_config_button.clicked.connect(lambda: self.configure_remote_profile(False))
        advanced.addWidget(full_config_button, 2, 4, 1, 2)
        advanced.addWidget(QLabel("SSH 地址"), 0, 0)
        self.remote_host_edit = QLineEdit(); self.remote_host_edit.setPlaceholderText("IP 或域名")
        self.remote_host_edit.textChanged.connect(self._update_remote_ready_state)
        advanced.addWidget(self.remote_host_edit, 0, 1, 1, 2)
        self.remote_port_spin = QSpinBox(); self.remote_port_spin.setRange(1, 65535); self.remote_port_spin.setValue(22)
        self.remote_port_spin.setMaximumWidth(85); advanced.addWidget(self.remote_port_spin, 0, 3)
        advanced.addWidget(QLabel("用户"), 0, 4)
        self.remote_user_edit = QLineEdit("root"); self.remote_user_edit.setMaximumWidth(120)
        advanced.addWidget(self.remote_user_edit, 0, 5)
        advanced.addWidget(QLabel("认证"), 0, 6)
        self.remote_auth_combo = QComboBox()
        self.remote_auth_combo.addItem("私钥", RemoteAuthType.PRIVATE_KEY.value)
        self.remote_auth_combo.addItem("密码", RemoteAuthType.PASSWORD.value)
        self.remote_auth_combo.addItem("SSH Agent", RemoteAuthType.AGENT.value)
        self.remote_auth_combo.currentIndexChanged.connect(self._toggle_remote_key_input)
        advanced.addWidget(self.remote_auth_combo, 0, 7, 1, 2)

        advanced.addWidget(QLabel("私钥"), 1, 0)
        self.remote_key_edit = QLineEdit(); self.remote_key_edit.setPlaceholderText("私钥路径；使用密码或 Agent 时可留空")
        advanced.addWidget(self.remote_key_edit, 1, 1, 1, 2)
        key_button = QPushButton("选择…"); key_button.clicked.connect(self._choose_remote_key)
        self.remote_key_button = key_button; advanced.addWidget(key_button, 1, 3)
        advanced.addWidget(QLabel("ComfyUI"), 1, 4)
        self.remote_comfy_host_edit = QLineEdit("127.0.0.1"); self.remote_comfy_host_edit.setMaximumWidth(130)
        advanced.addWidget(self.remote_comfy_host_edit, 1, 5)
        self.remote_comfy_port_spin = QSpinBox(); self.remote_comfy_port_spin.setRange(1, 65535); self.remote_comfy_port_spin.setValue(8188)
        self.remote_comfy_port_spin.setMaximumWidth(90); advanced.addWidget(self.remote_comfy_port_spin, 1, 6)
        advanced.addWidget(QLabel("模型覆盖"), 1, 7)
        self.remote_model_file_edit = QLineEdit(); self.remote_model_file_edit.setPlaceholderText("通常留空，自动使用工作流中的模型")
        advanced.addWidget(self.remote_model_file_edit, 1, 8)
        advanced.setColumnStretch(1, 1); advanced.setColumnStretch(8, 1)
        self.remote_advanced_panel.setVisible(False)
        self.remote_advanced_button.toggled.connect(self.remote_advanced_panel.setVisible)
        self.remote_advanced_button.toggled.connect(
            lambda checked: self.remote_advanced_button.setText(
                "隐藏高级连接设置" if checked else "显示高级连接设置"
            )
        )
        outer.addWidget(self.remote_advanced_panel)

        quick_hint = QLabel(
            "优云智算：依次复制实例卡片里的“ssh登录指令”和“密码”即可。"
            "密码勾选后保存在 Windows 凭据管理器，不写入项目数据库。"
            "连接后会自动探测 127.0.0.1:8188，并读取镜像自带的 01–20 号工作流。"
        )
        quick_hint.setWordWrap(True); quick_hint.setStyleSheet("color: #666")
        outer.addWidget(quick_hint)

        layout = QHBoxLayout()
        layout.addWidget(QLabel("云端工作流"))
        self.workflow_profile_combo = QComboBox(); self.workflow_profile_combo.setMinimumWidth(190)
        self.workflow_profile_combo.currentIndexChanged.connect(self._workflow_selection_changed)
        layout.addWidget(self.workflow_profile_combo)
        workflow_import = QPushButton("导入其他工作流…")
        workflow_import.clicked.connect(self.import_workflow_profile); layout.addWidget(workflow_import)
        self.remote_generate_button = QPushButton("生成并自动下载")
        self.remote_generate_button.setProperty("buttonRole", "success")
        self.remote_generate_button.clicked.connect(self.generate_remote)
        layout.addWidget(self.remote_generate_button)
        self.remote_resume_button = QPushButton("恢复未完成")
        self.remote_resume_button.clicked.connect(self.resume_remote_generation)
        layout.addWidget(self.remote_resume_button)
        self.remote_cancel_button = QPushButton("取消排队")
        self.remote_cancel_button.setProperty("buttonRole", "danger")
        self.remote_cancel_button.clicked.connect(self.cancel_remote_generation)
        self.remote_cancel_button.setEnabled(False)
        layout.addWidget(self.remote_cancel_button)
        self.remote_open_button = QPushButton("查看生成图片")
        self.remote_open_button.clicked.connect(self.show_image_gallery)
        layout.addWidget(self.remote_open_button)
        self.remote_progress = QProgressBar(); self.remote_progress.setRange(0, 100); self.remote_progress.setValue(0)
        self.remote_progress.setMaximumWidth(130); layout.addWidget(self.remote_progress)
        self.remote_status = QLabel("未配置")
        self.remote_status.setMinimumWidth(180); layout.addWidget(self.remote_status, 1)
        outer.addLayout(layout)
        self.model_combo.currentIndexChanged.connect(self._load_current_remote_model_alias)
        self._set_combo_data(self.remote_provider_combo, DEFAULT_PROVIDER_PRESET_ID)
        self._apply_remote_provider_preset()
        self._toggle_remote_key_input()
        self._refresh_remote_controls()
        return group

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
        self.center_tabs = tabs
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
        el.addWidget(QLabel("质量预设增强会始终进入最终 Prompt；上下文增强由动作和场景规则触发。"))
        self.quality_enhancement_summary = QLabel()
        self.quality_enhancement_summary.setWordWrap(True)
        self.quality_enhancement_summary.setStyleSheet(
            "background: #eef4ff; color: #234a83; border: 1px solid #c9daf8; border-radius: 5px; padding: 7px;"
        )
        el.addWidget(self.quality_enhancement_summary)
        el.addWidget(QLabel("上下文可编辑增强（可关闭、编辑和锁定）"))
        self.enhancement_empty_label = QLabel(
            "当前描述没有触发额外的动作或场景规则。这不是错误；上方质量预设增强仍然有效。"
        )
        self.enhancement_empty_label.setWordWrap(True)
        self.enhancement_empty_label.setStyleSheet("color: #777; padding: 8px;")
        el.addWidget(self.enhancement_empty_label)
        self.enhancement_table = QTableWidget(0, 5)
        self.enhancement_table.setHorizontalHeaderLabels(["启用", "类型", "来源规则", "英文内容", "锁定"])
        self.enhancement_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        el.addWidget(self.enhancement_table)
        apply_enh = QPushButton("应用增强修改"); apply_enh.clicked.connect(self.apply_enhancement_changes); el.addWidget(apply_enh)
        self.enhancement_tab_index = tabs.addTab(enhancements, "增强内容")
        self.image_gallery = ImageGalleryWidget(self.repository, self._generation_output_root)
        self.image_gallery.status_message.connect(lambda message: self.statusBar().showMessage(message, 4000))
        tabs.addTab(self.image_gallery, "生成图片")
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
        self.batch.setToolTip("一次提交生成并下载的图片数量")
        self.batch.valueChanged.connect(self.on_batch_size_changed)
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
        quality = self.configs.get_quality(j.quality_profile_id)
        model = self.configs.get_model(j.model_profile_id)
        quality_tags = model.positive_prefix + quality.all_tags()
        self.quality_enhancement_summary.setText(
            f"当前质量预设：{quality.display_name}\n"
            + (", ".join(quality_tags) if quality_tags else "此预设不添加额外质量词。")
        )
        self.enhancement_empty_label.setVisible(not j.enhancements)
        self.enhancement_table.setVisible(bool(j.enhancements))
        self.center_tabs.setTabText(
            self.enhancement_tab_index,
            f"增强内容 ({len(j.enhancements)})",
        )
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

    def on_batch_size_changed(self, value: int) -> None:
        if self._updating:
            return
        self.job.generation_params.batch_size = value
        self.statusBar().showMessage(f"本次任务将批量生成 {value} 张图片。", 3000)

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

    def _choose_remote_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 SSH 私钥")
        if path:
            self.remote_key_edit.setText(path)

    def paste_and_parse_ssh_command(self) -> None:
        command = self.remote_ssh_command_edit.text().strip()
        if not command:
            command = QApplication.clipboard().text().strip()
            if command:
                self.remote_ssh_command_edit.setText(command)
        try:
            parsed = parse_ssh_command(command)
        except Exception as exc:
            self._show_error("无法识别 SSH 登录指令", exc)
            return
        self.remote_host_edit.setText(parsed.host)
        self.remote_port_spin.setValue(parsed.port)
        self.remote_user_edit.setText(parsed.user)
        if not self.remote_name_edit.text().strip():
            self.remote_name_edit.setText("优云智算")
        self.remote_status.setText(
            f"已识别 {parsed.user}@{parsed.host}:{parsed.port}；请再粘贴控制台密码并连接测试"
        )

    def connect_remote_quickly(self) -> None:
        try:
            if not self.remote_host_edit.text().strip():
                self.paste_and_parse_ssh_command()
            if not self.remote_host_edit.text().strip():
                return
            if self.remote_auth_combo.currentData() == RemoteAuthType.PASSWORD.value:
                if not self.remote_password_edit.text():
                    clipboard_text = QApplication.clipboard().text().strip()
                    if clipboard_text and not clipboard_text.casefold().startswith("ssh "):
                        self.remote_password_edit.setText(clipboard_text)
                if not self.remote_password_edit.text():
                    raise ValueError("请复制优云智算实例卡片中的密码，再点击“粘贴密码”。")
            self._save_remote_profile_from_form(True)
            self.test_remote_connection()
        except Exception as exc:
            self._show_error("无法连接云主机", exc)

    def _toggle_remote_key_input(self) -> None:
        is_key = self.remote_auth_combo.currentData() == RemoteAuthType.PRIVATE_KEY.value
        self.remote_key_edit.setEnabled(is_key)
        self.remote_key_button.setEnabled(is_key)

    def _apply_remote_provider_preset(self) -> None:
        if self._remote_form_loading:
            return
        preset = get_provider_preset(self.remote_provider_combo.currentData() or DEFAULT_PROVIDER_PRESET_ID)
        self.remote_port_spin.setValue(preset.ssh_port)
        self.remote_user_edit.setText(preset.ssh_user)
        self._set_combo_data(self.remote_auth_combo, preset.auth_type.value)
        self.remote_comfy_host_edit.setText(preset.comfy_host)
        self.remote_comfy_port_spin.setValue(preset.comfy_port)
        if preset.auth_type != RemoteAuthType.PRIVATE_KEY:
            self.remote_key_edit.clear()
        if not self.remote_name_edit.text().strip():
            default_names = {
                "compshare_container": "优云智算",
                "compshare_ubuntu": "优云智算 Ubuntu",
                "custom": "自定义云主机",
            }
            self.remote_name_edit.setText(default_names.get(preset.id, preset.display_name))
        self._toggle_remote_key_input()
        self.remote_status.setText(preset.notes)

    def _clear_remote_form(self) -> None:
        self._remote_form_loading = True
        self.remote_profile_combo.setCurrentIndex(-1)
        self._direct_remote_id = ""
        self.remote_name_edit.clear(); self.remote_host_edit.clear(); self.remote_key_edit.clear()
        self.remote_ssh_command_edit.clear(); self.remote_password_edit.clear()
        self.remote_model_file_edit.clear()
        self._set_combo_data(self.remote_provider_combo, DEFAULT_PROVIDER_PRESET_ID)
        self._remote_form_loading = False
        self._apply_remote_provider_preset()
        self.remote_status.setText("请直接填写 SSH 信息，然后保存或连接测试")

    def _load_remote_form_from_selection(self) -> None:
        if self._remote_form_loading:
            return
        profile_id = self.remote_profile_combo.currentData()
        if not profile_id:
            return
        try:
            profile = self.repository.get_remote_profile(profile_id)
        except Exception as exc:
            self._show_error("读取云主机配置失败", exc)
            return
        self._remote_form_loading = True
        self._direct_remote_id = profile.id
        self._set_combo_data(self.remote_provider_combo, profile.provider_preset_id)
        self.remote_name_edit.setText(profile.display_name)
        self.remote_host_edit.setText(profile.ssh_host); self.remote_port_spin.setValue(profile.ssh_port)
        self.remote_user_edit.setText(profile.ssh_user)
        self.remote_ssh_command_edit.setText(
            f"ssh -p {profile.ssh_port} {profile.ssh_user}@{profile.ssh_host}"
        )
        self._set_combo_data(self.remote_auth_combo, profile.auth_type.value)
        self.remote_key_edit.setText(profile.private_key_path)
        self.remote_comfy_host_edit.setText(profile.comfy_host); self.remote_comfy_port_spin.setValue(profile.comfy_port)
        self._remote_form_loading = False
        self._toggle_remote_key_input()
        self._load_current_remote_model_alias()
        try:
            saved_password = self.credential_store.read_password(profile.id)
        except CredentialStoreError as exc:
            saved_password = ""
            self.statusBar().showMessage(str(exc), 5000)
        self.remote_password_edit.setText(saved_password)
        remember = bool(self.repository.get_setting(
            f"remember_remote_password:{profile.id}",
            bool(saved_password) or self.credential_store.available,
        ))
        self.remote_remember_password.setChecked(remember and self.credential_store.available)
        self.repository.set_setting("last_remote_profile_id", profile.id)

    def _load_current_remote_model_alias(self) -> None:
        if self._remote_form_loading or not self._direct_remote_id:
            return
        try:
            profile = self.repository.get_remote_profile(self._direct_remote_id)
            model = self.configs.get_model(self.model_combo.currentData())
            self.remote_model_file_edit.setText(profile.model_aliases.get(model.checkpoint_logical_name, ""))
        except Exception:
            self.remote_model_file_edit.clear()

    def _save_remote_profile_from_form(self, silent: bool = False) -> RemoteProfile:
        host = self.remote_host_edit.text().strip()
        user = self.remote_user_edit.text().strip()
        if not host:
            raise ValueError("请直接填写 SSH 地址。")
        if not user:
            raise ValueError("SSH 用户不能为空。")
        existing = None
        if self._direct_remote_id:
            try:
                existing = self.repository.get_remote_profile(self._direct_remote_id)
            except KeyError:
                existing = None
        fingerprint = ""
        aliases: dict[str, str] = {}
        if existing:
            aliases.update(existing.model_aliases)
            if existing.ssh_host == host and existing.ssh_port == self.remote_port_spin.value():
                fingerprint = existing.known_host_fingerprint
        model = self.configs.get_model(self.model_combo.currentData())
        model_filename = self.remote_model_file_edit.text().strip()
        if model_filename:
            aliases[model.checkpoint_logical_name] = model_filename
        values = {
            "provider_preset_id": self.remote_provider_combo.currentData() or DEFAULT_PROVIDER_PRESET_ID,
            "display_name": self.remote_name_edit.text().strip() or host,
            "ssh_host": host,
            "ssh_port": self.remote_port_spin.value(),
            "ssh_user": user,
            "auth_type": RemoteAuthType(self.remote_auth_combo.currentData()),
            "private_key_path": self.remote_key_edit.text().strip(),
            "known_host_fingerprint": fingerprint,
            "comfy_host": self.remote_comfy_host_edit.text().strip() or "127.0.0.1",
            "comfy_port": self.remote_comfy_port_spin.value(),
            "model_aliases": aliases,
            "enabled": True,
        }
        if existing:
            values.update(
                id=existing.id,
                startup_mode=existing.startup_mode,
                startup_command=existing.startup_command,
            )
        profile = RemoteProfile(**values)
        self.repository.save_remote_profile(profile)
        self.repository.set_setting("last_remote_profile_id", profile.id)
        self.repository.set_setting("remote_auto_connect", self.remote_auto_connect.isChecked())
        self.repository.set_setting(
            f"remember_remote_password:{profile.id}",
            self.remote_remember_password.isChecked(),
        )
        if profile.auth_type == RemoteAuthType.PASSWORD:
            if self.remote_remember_password.isChecked() and self.remote_password_edit.text():
                self.credential_store.save_password(
                    profile.id,
                    f"{profile.ssh_user}@{profile.ssh_host}",
                    self.remote_password_edit.text(),
                )
            elif not self.remote_remember_password.isChecked():
                self.credential_store.delete_password(profile.id)
        self._direct_remote_id = profile.id
        self._refresh_remote_controls(selected_remote_id=profile.id)
        if not silent:
            self.statusBar().showMessage("SSH 与 ComfyUI 连接信息已保存。", 4000)
        return profile

    def save_remote_connection(self) -> None:
        try:
            self._save_remote_profile_from_form(False)
        except Exception as exc:
            self._show_error("保存连接失败", exc)

    def _update_remote_ready_state(self) -> None:
        if not hasattr(self, "remote_generate_button"):
            return
        workflow_supported = False
        workflow_id = self.workflow_profile_combo.currentData()
        if workflow_id:
            try:
                workflow_supported = (
                    self.repository.get_workflow_profile(workflow_id).workflow_kind == "txt2img_basic"
                )
            except Exception:
                workflow_supported = False
        ready = bool(self.remote_host_edit.text().strip()) and workflow_supported
        self.remote_generate_button.setEnabled(ready and self._active_generation_worker is None)

    def _refresh_remote_controls(self, selected_remote_id: str = "", selected_workflow_id: str = "") -> None:
        if not hasattr(self, "remote_profile_combo"):
            return
        current_remote = (
            selected_remote_id
            or self.remote_profile_combo.currentData()
            or self.repository.get_setting("last_remote_profile_id", "")
            or ""
        )
        current_workflow = selected_workflow_id or self.workflow_profile_combo.currentData() or ""
        self._remote_form_loading = True
        self.remote_profile_combo.clear()
        for profile in self.repository.list_remote_profiles(enabled_only=True):
            self.remote_profile_combo.addItem(profile.display_name, profile.id)
        self.workflow_profile_combo.clear()
        for profile in self.repository.list_workflow_profiles():
            suffix = " · V2 可直接生成" if profile.workflow_kind == "txt2img_basic" else " · 下一版本适配"
            self.workflow_profile_combo.addItem(profile.display_name + suffix, profile.id)
        self._set_combo_data(self.remote_profile_combo, current_remote)
        self._set_combo_data(self.workflow_profile_combo, current_workflow)
        self._remote_form_loading = False
        if self.remote_profile_combo.currentData():
            self._load_remote_form_from_selection()
        active_count = len(self.repository.list_active_generation_runs())
        self.remote_resume_button.setText(f"恢复未完成 ({active_count})" if active_count else "恢复未完成")
        ready = bool(self.remote_host_edit.text().strip()) and self.workflow_profile_combo.count() > 0
        self._update_remote_ready_state()
        if not ready:
            self.remote_status.setText("请填写 SSH 信息并导入基础文生图工作流")

    def configure_remote_profile(self, create_new: bool = True) -> None:
        profile = None
        if not create_new and self.remote_host_edit.text().strip():
            try:
                profile = self._save_remote_profile_from_form(True)
            except Exception as exc:
                self._show_error("读取云主机配置失败", exc)
                return
        dialog = RemoteProfileDialog(profile, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            result = dialog.result_profile()
            self.repository.save_remote_profile(result)
            self._refresh_remote_controls(selected_remote_id=result.id)
            self.statusBar().showMessage("云主机配置已保存。", 4000)
        except Exception as exc:
            self._show_error("保存云主机配置失败", exc)

    def import_workflow_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 ComfyUI API 工作流", "", "JSON (*.json)")
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("prompt"), dict):
                payload = payload["prompt"]
            if not isinstance(payload, dict) or not payload:
                raise ValueError("工作流 JSON 必须是 ComfyUI API Format 节点对象。")
            profile, missing = build_auto_workflow_profile(
                payload,
                Path(path),
                self.model_combo.currentData() or "",
            )
            if missing:
                QMessageBox.information(
                    self,
                    "需要校准工作流",
                    "软件无法完整识别以下基础文生图字段：\n"
                    + "、".join(missing)
                    + "\n\n接下来可以手工指定节点 ID。",
                )
                dialog = WorkflowProfileDialog(payload, Path(path), self)
                if dialog.exec() != QDialog.Accepted:
                    return
                profile = dialog.result_profile()
            self.repository.save_workflow_profile(profile)
            self._refresh_remote_controls(selected_workflow_id=profile.id)
            if profile.workflow_kind == "txt2img_basic":
                message = (
                    f"已自动识别基础文生图工作流：采样节点 {profile.bindings['seed'].node_id}，"
                    f"正向节点 {profile.bindings['positive_prompt'].node_id}，"
                    f"检测到 {len(profile.lora_slots)} 个 LoRA 插槽。"
                )
                QMessageBox.information(self, "工作流识别完成", message)
                self.statusBar().showMessage("基础文生图工作流已自动识别并导入。", 5000)
            else:
                QMessageBox.warning(
                    self,
                    "工作流已导入",
                    "该工作流不是软件当前保证兼容的基础文生图类型。仍允许选择和尝试执行，"
                    "但复杂节点链路可能需要后续版本支持。",
                )
        except Exception as exc:
            self._show_error("导入工作流失败", exc)

    def configure_output_root(self) -> None:
        current = self.repository.get_setting("generation_output_root", str(Path.home() / "Pictures" / "AnimaPromptStudio"))
        path = QFileDialog.getExistingDirectory(self, "选择生成图片根目录", current)
        if path:
            self.repository.set_setting("generation_output_root", path)
            self.image_gallery.refresh()
            self.remote_open_button.setEnabled(self.image_gallery.has_images)
            self.statusBar().showMessage(f"生成图片将保存到：{path}", 6000)

    def _generation_output_root(self) -> Path:
        return Path(self.repository.get_setting(
            "generation_output_root",
            str(Path.home() / "Pictures" / "AnimaPromptStudio"),
        ))

    def show_image_gallery(self, run_id: str = "") -> None:
        self.image_gallery.refresh(run_id if isinstance(run_id, str) else "")
        self.center_tabs.setCurrentWidget(self.image_gallery)
        self.remote_open_button.setEnabled(self.image_gallery.has_images)
        if not self.image_gallery.has_images:
            self.statusBar().showMessage("还没有可查看的生成图片。", 4000)

    def open_history_gallery(self) -> None:
        if self._gallery_server is None:
            self._gallery_server = GalleryServer(
                self.repository,
                self._generation_output_root,
            )
        url = self._gallery_server.start()
        QDesktopServices.openUrl(QUrl(url))
        self.statusBar().showMessage("已在系统浏览器中打开本地图片画廊。", 5000)

    def open_gallery_root(self) -> None:
        root = self._generation_output_root()
        root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    def _selected_remote_profile(self) -> RemoteProfile:
        return self._save_remote_profile_from_form(True)

    def _selected_workflow_profile(self):
        profile_id = self.workflow_profile_combo.currentData()
        if not profile_id:
            raise ValueError("请先导入 ComfyUI API 工作流。")
        profile = self.repository.get_workflow_profile(profile_id)
        return self._ensure_workflow_model_compatibility(profile)

    def _ensure_workflow_model_compatibility(self, profile):
        """Upgrade previously discovered profiles that predate model mapping."""
        if profile.compatible_model_profiles:
            return profile
        source_name = profile.source_path or profile.display_name or profile.id
        inferred = infer_workflow_model_profiles(profile.api_workflow, source_name)
        if inferred:
            profile.compatible_model_profiles = inferred
            self.repository.save_workflow_profile(profile)
        return profile

    def _workflow_selection_changed(self) -> None:
        profile_id = self.workflow_profile_combo.currentData()
        if not profile_id or self._active_generation_worker is not None:
            return
        try:
            profile = self._ensure_workflow_model_compatibility(
                self.repository.get_workflow_profile(profile_id)
            )
        except Exception:
            return
        if len(profile.compatible_model_profiles) == 1:
            self._set_combo_data(self.model_combo, profile.compatible_model_profiles[0])
        if profile.workflow_kind == "txt2img_basic":
            self.remote_status.setText("该工作流已完成真实测试，V2 可直接生成")
        else:
            self.remote_status.setText("该工作流已识别并保留，执行适配留到下一版本")
        self._update_remote_ready_state()

    def _request_remote_credentials(self, profile: RemoteProfile) -> RemoteCredentials | None:
        if profile.auth_type == RemoteAuthType.PASSWORD:
            cached_password = self.remote_password_edit.text()
            if cached_password:
                return RemoteCredentials(password=cached_password)
            password, accepted = QInputDialog.getText(
                self,
                "SSH 密码",
                f"请输入 {profile.ssh_user}@{profile.ssh_host} 的密码：",
                QLineEdit.Password,
            )
            if accepted:
                self.remote_password_edit.setText(password)
                return RemoteCredentials(password=password)
            return None
        if profile.auth_type == RemoteAuthType.PRIVATE_KEY:
            passphrase, accepted = QInputDialog.getText(
                self,
                "私钥口令",
                "如果私钥没有口令，请留空并确定：",
                QLineEdit.Password,
            )
            return RemoteCredentials(passphrase=passphrase) if accepted else None
        return RemoteCredentials()

    def test_remote_connection(self) -> None:
        try:
            profile = self._selected_remote_profile()
        except Exception as exc:
            self._show_error("无法测试连接", exc)
            return
        credentials = self._request_remote_credentials(profile)
        if credentials is None:
            return
        self.remote_test_button.setEnabled(False)
        self.remote_status.setText("正在连接 SSH…")
        worker = ConnectionTestWorker(profile, credentials)
        worker.fingerprint_required.connect(self._confirm_remote_fingerprint)
        worker.succeeded.connect(self._remote_connection_succeeded)
        worker.failed.connect(self._remote_connection_failed)
        worker.done.connect(self._remote_connection_done)
        self._start_remote_worker(worker)

    def _auto_connect_last_remote(self) -> None:
        if not hasattr(self, "remote_auto_connect") or not self.remote_auto_connect.isChecked():
            return
        profile_id = self.remote_profile_combo.currentData()
        if not profile_id or self._active_generation_worker is not None:
            return
        try:
            profile = self.repository.get_remote_profile(profile_id)
        except KeyError:
            return
        if not profile.known_host_fingerprint:
            self.remote_status.setText("已恢复上次云主机；首次连接仍需确认主机指纹")
            return
        if profile.auth_type == RemoteAuthType.PASSWORD and not self.remote_password_edit.text():
            self.remote_status.setText("已恢复上次云主机；请输入一次密码后即可自动连接")
            return
        self.remote_status.setText("正在自动连接上次云主机…")
        self.test_remote_connection()

    def _remote_connection_failed(self, message: str) -> None:
        self._remote_operation_failed("连接测试失败", message)

    def _remote_connection_done(self) -> None:
        self.remote_test_button.setEnabled(True)

    def _confirm_remote_fingerprint(self, profile: RemoteProfile, fingerprint: str) -> None:
        answer = QMessageBox.question(
            self,
            "确认 SSH 主机指纹",
            f"首次连接 {profile.ssh_host}。\n\n主机指纹：\n{fingerprint}\n\n请与云服务商控制台显示的指纹核对。确认保存吗？",
        )
        if answer != QMessageBox.Yes:
            self.remote_status.setText("未确认主机指纹")
            return
        profile.known_host_fingerprint = fingerprint
        self.repository.save_remote_profile(profile)
        self.remote_status.setText("主机指纹已保存，请再次连接测试")
        QTimer.singleShot(100, self.test_remote_connection)

    def _remote_connection_succeeded(self, report, discovered_workflows) -> None:
        imported_ids: list[str] = []
        basic_ids: list[str] = []
        for display_name, remote_path, workflow in discovered_workflows:
            try:
                profile, missing = build_auto_workflow_profile(
                    workflow,
                    Path(display_name + ".json"),
                )
                profile.source_path = remote_path
                if missing:
                    profile.notes = (
                        "通过 SSH 从优云智算镜像自动发现并转换；当前版本尚未识别字段："
                        + "、".join(missing)
                    )
                else:
                    profile.notes = "通过 SSH 从优云智算镜像自动发现并转换。"
                self.repository.save_workflow_profile(profile)
                imported_ids.append(profile.id)
                if not missing and profile.workflow_kind == "txt2img_basic":
                    basic_ids.append(profile.id)
            except Exception:
                log.exception("无法导入远端工作流 %s", remote_path)
        if imported_ids:
            self._refresh_remote_controls(selected_workflow_id=(basic_ids or imported_ids)[0])
        device = report.devices[0] if report.devices else "设备信息未知"
        self.remote_status.setText(
            f"已连接 · {device} · 队列 {report.queue_running + report.queue_pending}"
            + (
                f" · 自动发现 {len(imported_ids)} 个工作流，其中 {len(basic_ids)} 个结构识别为基础文生图"
                if imported_ids else ""
            )
        )
        self.statusBar().showMessage(
            "SSH 隧道和 ComfyUI API 连接正常。"
            + (
                f" 已导入镜像的 {len(imported_ids)} 个工作流，"
                f"其中 {len(basic_ids)} 个识别为基础文生图。"
                if imported_ids else ""
            ),
            8000,
        )

    def generate_remote(self) -> None:
        try:
            self._sync_and_recompile()
            self._refresh_results()
            profile = self._selected_remote_profile()
            workflow = self._selected_workflow_profile()
            if not profile.known_host_fingerprint:
                raise ValueError("请先执行“连接测试”并确认 SSH 主机指纹。")
            if workflow.workflow_kind != "txt2img_basic":
                raise ValueError(
                    "这个复杂工作流已经识别并保留在列表中，但执行适配安排在下一版本。"
                    "V2 请使用标有“V2 可直接生成”的工作流。"
                )
            model_profile = self.configs.get_model(self.job.model_profile_id)
            output_root = Path(self.repository.get_setting(
                "generation_output_root",
                str(Path.home() / "Pictures" / "AnimaPromptStudio"),
            ))
            if not self.job.positive_prompt.strip():
                raise ValueError("当前正向提示词为空，请先翻译并编译。")
            params = self.job.generation_params
            answer = QMessageBox.question(
                self,
                "确认远程生成",
                f"云主机：{profile.display_name}\n"
                f"工作流：{workflow.display_name}\n"
                f"模型：{model_profile.display_name}\n"
                f"尺寸：{params.width} × {params.height}\n"
                f"批量：{params.batch_size}\n"
                f"保存根目录：{output_root}\n\n"
                "提交后，本次任务将使用当前参数快照。是否继续？",
            )
            if answer != QMessageBox.Yes:
                return
            credentials = self._request_remote_credentials(profile)
            if credentials is None:
                return
            self.repository.save_job(self.job)
            job_snapshot = self.job.model_copy(deep=True)
            worker = GenerationWorker(
                job=job_snapshot,
                run=None,
                profile=profile,
                workflow_profile=workflow,
                checkpoint_logical_name=model_profile.checkpoint_logical_name,
                credentials=credentials,
                output_root=output_root,
            )
            self._launch_generation_worker(worker)
        except Exception as exc:
            self._show_error("无法开始远程生成", exc)

    def resume_remote_generation(self) -> None:
        active = [run for run in self.repository.list_active_generation_runs() if run.remote_prompt_id]
        if not active:
            QMessageBox.information(self, "没有可恢复任务", "当前没有已经提交到 ComfyUI 的未完成任务。")
            return
        run = active[0]
        try:
            profile = self.repository.get_remote_profile(run.remote_profile_id)
            workflow = self.repository.get_workflow_profile(run.workflow_profile_id)
            credentials = self._request_remote_credentials(profile)
            if credentials is None:
                return
            output_root = Path(self.repository.get_setting(
                "generation_output_root",
                str(Path.home() / "Pictures" / "AnimaPromptStudio"),
            ))
            worker = GenerationWorker(
                job=None,
                run=run,
                profile=profile,
                workflow_profile=workflow,
                checkpoint_logical_name="",
                credentials=credentials,
                output_root=output_root,
            )
            self._launch_generation_worker(worker)
        except Exception as exc:
            self._show_error("无法恢复远程任务", exc)

    def _launch_generation_worker(self, worker: GenerationWorker) -> None:
        self._active_generation_worker = worker
        self.remote_generate_button.setEnabled(False)
        self.remote_resume_button.setEnabled(False)
        self.remote_cancel_button.setEnabled(True)
        self.remote_progress.setValue(0)
        worker.updated.connect(self._remote_generation_updated)
        worker.succeeded.connect(self._remote_generation_succeeded)
        worker.failed.connect(self._remote_generation_failed)
        worker.done.connect(self._remote_generation_done)
        self._start_remote_worker(worker)

    def _remote_generation_updated(self, run) -> None:
        self.repository.save_generation_run(run)
        self.remote_progress.setValue(round(run.progress * 100))
        self.remote_status.setText(run.status_message or run.state.value)
        self.remote_cancel_button.setEnabled(run.state.value in {"connecting", "preparing", "queued"})
        self._refresh_remote_controls()

    def _remote_generation_succeeded(self, run, artifacts) -> None:
        self.repository.save_generation_run(run)
        for artifact in artifacts:
            self.repository.save_generation_artifact(artifact)
        self._last_output_dir = run.output_dir
        self.show_image_gallery(run.id)
        self.remote_status.setText(f"完成 · 已下载 {len(artifacts)} 张图片")
        self.statusBar().showMessage(f"远程生图完成：{run.output_dir}", 10000)

    def _remote_generation_failed(self, run, message: str) -> None:
        self.repository.save_generation_run(run)
        self.remote_status.setText("远程生成失败")
        QMessageBox.critical(self, "远程生成失败", message)

    def _remote_generation_done(self) -> None:
        self._active_generation_worker = None
        self.remote_cancel_button.setEnabled(False)
        self.remote_resume_button.setEnabled(True)
        self._refresh_remote_controls()

    def cancel_remote_generation(self) -> None:
        if self._active_generation_worker:
            self._active_generation_worker.cancel()
            self.remote_status.setText("正在请求取消…")

    def open_remote_output(self) -> None:
        if self._last_output_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_output_dir))

    def _start_remote_worker(self, worker) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda thread=thread, worker=worker: self._remote_worker_finished(thread, worker))
        self._remote_threads.append(thread)
        self._remote_workers.append(worker)
        thread.start()

    def _remote_worker_finished(self, thread: QThread, worker) -> None:
        if thread in self._remote_threads:
            self._remote_threads.remove(thread)
        if worker in self._remote_workers:
            self._remote_workers.remove(worker)

    def _remote_operation_failed(self, title: str, message: str) -> None:
        self.remote_status.setText(title)
        QMessageBox.critical(self, title, message)

    def _show_error(self, title: str, exc: Exception) -> None:
        log.exception(title, exc_info=exc); QMessageBox.critical(self, title, str(exc))

    def closeEvent(self, event) -> None:
        if self._active_generation_worker:
            self._active_generation_worker.cancel()
        still_running = []
        for thread in list(self._remote_threads):
            thread.quit()
            if not thread.wait(3000):
                still_running.append(thread)
        if still_running:
            event.ignore()
            self.statusBar().showMessage("正在安全结束远程任务，请稍后再次关闭窗口。", 5000)
            return
        if self._gallery_server is not None:
            self._gallery_server.stop()
        self.repository.close(); super().closeEvent(event)
