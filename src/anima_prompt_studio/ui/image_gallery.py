from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from anima_prompt_studio.repositories import SQLiteRepository


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass
class GalleryBatch:
    run_id: str
    output_dir: Path
    created_at: datetime
    project_name: str = "未命名项目"
    model_profile_id: str = ""
    positive_prompt: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    image_paths: list[Path] = field(default_factory=list)

    @property
    def title(self) -> str:
        stamp = self.created_at.astimezone().strftime("%m-%d %H:%M")
        model = self.model_profile_id.replace("anima_", "").replace("_v1", "") or "未知模型"
        return f"{stamp} · {self.project_name} · {model} · {len(self.image_paths)} 张"


def load_gallery_batches(
    repository: SQLiteRepository,
    output_root: Path,
    limit: int = 200,
) -> list[GalleryBatch]:
    """Load recent image batches from the database, then recover missing ones from manifests."""
    batches: dict[str, GalleryBatch] = {}
    for run in repository.list_generation_runs(limit=limit):
        paths = _existing_image_paths(
            Path(artifact.local_path) for artifact in repository.list_generation_artifacts(run.id)
        )
        if not paths:
            continue
        snapshot = run.request_json.get("prompt_job", {})
        params = snapshot.get("generation_params", {}) if isinstance(snapshot, dict) else {}
        batches[run.id] = GalleryBatch(
            run_id=run.id,
            output_dir=Path(run.output_dir) if run.output_dir else paths[0].parent,
            created_at=run.completed_at or run.created_at,
            project_name=str(snapshot.get("project_name") or "未命名项目"),
            model_profile_id=str(snapshot.get("model_profile_id") or ""),
            positive_prompt=str(snapshot.get("positive_prompt") or ""),
            parameters=params if isinstance(params, dict) else {},
            image_paths=paths,
        )

    root = output_root.expanduser()
    if root.is_dir():
        manifests = []
        try:
            manifests = sorted(
                root.rglob("manifest.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )[:limit]
        except OSError:
            manifests = []
        for manifest_path in manifests:
            recovered = _batch_from_manifest(manifest_path, root)
            if recovered and recovered.run_id not in batches:
                batches[recovered.run_id] = recovered

        tracked = {
            str(path.resolve()).casefold()
            for batch in batches.values()
            for path in batch.image_paths
        }
        orphan_folders: dict[Path, list[Path]] = {}
        try:
            candidates = (path for path in root.rglob("*") if path.suffix.casefold() in IMAGE_SUFFIXES)
            for index, path in enumerate(candidates):
                if index >= 3000:
                    break
                if not path.is_file() or str(path.resolve()).casefold() in tracked:
                    continue
                orphan_folders.setdefault(path.parent, []).append(path)
        except OSError:
            orphan_folders = {}
        for folder, paths in orphan_folders.items():
            try:
                relative = folder.relative_to(root)
                project = relative.parts[0] if relative.parts else "未分类"
                model = next((part for part in relative.parts if part.startswith("anima_")), "")
                created = datetime.fromtimestamp(max(path.stat().st_mtime for path in paths)).astimezone()
            except (OSError, ValueError):
                continue
            run_id = "folder:" + str(folder.resolve())
            batches[run_id] = GalleryBatch(
                run_id=run_id,
                output_dir=folder,
                created_at=created,
                project_name=project,
                model_profile_id=model,
                image_paths=_existing_image_paths(paths),
            )

    return sorted(batches.values(), key=lambda batch: batch.created_at, reverse=True)[:limit]


def _batch_from_manifest(manifest_path: Path, output_root: Path) -> GalleryBatch | None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        run = payload.get("generation_run", {})
        job = payload.get("prompt_job", {})
        run_id = str(run.get("id") or manifest_path.parent)
        raw_paths = []
        for artifact in payload.get("artifacts", []):
            path = Path(str(artifact.get("local_path") or ""))
            if not path.is_absolute():
                path = manifest_path.parent / path
            raw_paths.append(path)
        paths = _existing_image_paths(raw_paths)
        if not paths:
            paths = _existing_image_paths(manifest_path.parent.iterdir())
        if not paths:
            return None
        created_at = _parse_datetime(run.get("completed_at") or run.get("created_at"), manifest_path)
        try:
            relative = manifest_path.parent.relative_to(output_root)
            project_name = relative.parts[0] if relative.parts else "未命名项目"
        except ValueError:
            project_name = "未命名项目"
        return GalleryBatch(
            run_id=run_id,
            output_dir=manifest_path.parent,
            created_at=created_at,
            project_name=str(job.get("project_name") or project_name),
            model_profile_id=str(job.get("model_profile") or job.get("model_profile_id") or ""),
            positive_prompt=str(job.get("positive_prompt") or ""),
            parameters=job if isinstance(job, dict) else {},
            image_paths=paths,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _existing_image_paths(paths) -> list[Path]:
    unique: dict[str, Path] = {}
    for path in paths:
        candidate = Path(path)
        if candidate.suffix.casefold() not in IMAGE_SUFFIXES or not candidate.is_file():
            continue
        try:
            key = str(candidate.resolve()).casefold()
        except OSError:
            key = str(candidate).casefold()
        unique[key] = candidate
    return sorted(unique.values(), key=lambda path: path.name.casefold())


def _parse_datetime(value: Any, fallback_path: Path) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone()
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_path.stat().st_mtime).astimezone()


class PreviewLabel(QLabel):
    double_clicked = Signal()

    def __init__(self) -> None:
        super().__init__("还没有生成图片")
        self._source = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 300)
        self.setStyleSheet("background: #17191d; color: #9aa0aa; border-radius: 6px;")

    def set_image(self, path: Path | None) -> None:
        self._source = QPixmap()
        if path is not None:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            image = reader.read()
            if not image.isNull():
                self._source = QPixmap.fromImage(image)
        self._render()

    def _render(self) -> None:
        if self._source.isNull():
            self.setPixmap(QPixmap())
            self.setText("还没有可预览的图片")
            return
        self.setText("")
        target = self.size() - QSize(16, 16)
        self.setPixmap(self._source.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self._source.isNull():
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class ImageGalleryWidget(QWidget):
    status_message = Signal(str)

    def __init__(
        self,
        repository: SQLiteRepository,
        output_root: Callable[[], Path],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.output_root = output_root
        self.batches: list[GalleryBatch] = []
        self._current_batch: GalleryBatch | None = None
        self._current_path: Path | None = None

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("生成批次"))
        self.batch_combo = QComboBox(); self.batch_combo.setMinimumWidth(290)
        self.batch_combo.currentIndexChanged.connect(self._batch_changed)
        top.addWidget(self.batch_combo, 1)
        refresh = QPushButton("刷新"); refresh.clicked.connect(self.refresh); top.addWidget(refresh)
        layout.addLayout(top)

        self.preview = PreviewLabel(); self.preview.double_clicked.connect(self.open_current_image)
        layout.addWidget(self.preview, 1)

        navigation = QHBoxLayout()
        self.previous_button = QPushButton("← 上一张"); self.previous_button.clicked.connect(self.previous_image)
        self.next_button = QPushButton("下一张 →"); self.next_button.clicked.connect(self.next_image)
        self.open_button = QPushButton("查看原图"); self.open_button.clicked.connect(self.open_current_image)
        self.folder_button = QPushButton("打开所在文件夹"); self.folder_button.clicked.connect(self.open_current_folder)
        self.copy_button = QPushButton("复制路径"); self.copy_button.clicked.connect(self.copy_current_path)
        for button in (self.previous_button, self.next_button, self.open_button, self.folder_button, self.copy_button):
            navigation.addWidget(button)
        navigation.addStretch()
        layout.addLayout(navigation)

        self.details = QTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(105)
        self.details.setPlaceholderText("选择图片后会显示模型、尺寸、采样参数、Seed 和提示词。")
        layout.addWidget(self.details)

        self.thumbnails = QListWidget()
        self.thumbnails.setViewMode(QListWidget.IconMode)
        self.thumbnails.setFlow(QListWidget.LeftToRight)
        self.thumbnails.setWrapping(False)
        self.thumbnails.setMovement(QListWidget.Static)
        self.thumbnails.setResizeMode(QListWidget.Adjust)
        self.thumbnails.setIconSize(QSize(104, 104))
        self.thumbnails.setGridSize(QSize(126, 132))
        self.thumbnails.setMaximumHeight(150)
        self.thumbnails.currentRowChanged.connect(self._image_changed)
        self.thumbnails.itemDoubleClicked.connect(lambda _item: self.open_current_image())
        layout.addWidget(self.thumbnails)
        self._update_action_state()

    @property
    def has_images(self) -> bool:
        return any(batch.image_paths for batch in self.batches)

    @property
    def current_image_path(self) -> Path | None:
        return self._current_path

    def refresh(self, select_run_id: str = "") -> None:
        current_run_id = select_run_id or self.batch_combo.currentData() or ""
        self.batches = load_gallery_batches(self.repository, self.output_root())
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        for batch in self.batches:
            self.batch_combo.addItem(batch.title, batch.run_id)
        index = self.batch_combo.findData(current_run_id)
        self.batch_combo.setCurrentIndex(index if index >= 0 else (0 if self.batches else -1))
        self.batch_combo.blockSignals(False)
        self._batch_changed()

    def _batch_changed(self) -> None:
        index = self.batch_combo.currentIndex()
        self._current_batch = self.batches[index] if 0 <= index < len(self.batches) else None
        self.thumbnails.blockSignals(True)
        self.thumbnails.clear()
        if self._current_batch:
            for path in self._current_batch.image_paths:
                item = QListWidgetItem(self._thumbnail_icon(path), path.name)
                item.setData(Qt.UserRole, str(path))
                item.setToolTip(str(path))
                self.thumbnails.addItem(item)
        self.thumbnails.blockSignals(False)
        if self.thumbnails.count():
            self.thumbnails.setCurrentRow(0)
            self._image_changed(0)
        else:
            self._image_changed(-1)

    def _image_changed(self, row: int) -> None:
        item = self.thumbnails.item(row) if row >= 0 else None
        self._current_path = Path(item.data(Qt.UserRole)) if item else None
        self.preview.set_image(self._current_path)
        self._update_details()
        self._update_action_state()

    def _update_details(self) -> None:
        if not self._current_batch or not self._current_path:
            self.details.clear()
            return
        batch = self._current_batch
        params = batch.parameters
        reader = QImageReader(str(self._current_path))
        size = reader.size()
        width = params.get("width") or (size.width() if size.isValid() else "?")
        height = params.get("height") or (size.height() if size.isValid() else "?")
        values = [f"{self._current_path.name}  ·  {width}×{height}"]
        parameter_line = "  ·  ".join(
            value for value in (
                batch.model_profile_id,
                f"Steps {params.get('steps')}" if params.get("steps") is not None else "",
                f"CFG {params.get('cfg')}" if params.get("cfg") is not None else "",
                str(params.get("sampler") or params.get("sampler_name") or ""),
                f"Seed {params.get('seed')}" if params.get("seed") is not None else "",
            ) if value
        )
        if parameter_line:
            values.append(parameter_line)
        if batch.positive_prompt:
            values.append(batch.positive_prompt)
        self.details.setPlainText("\n".join(values))
        self.details.setToolTip(str(self._current_path))

    def _update_action_state(self) -> None:
        enabled = self._current_path is not None and self._current_path.is_file()
        for button in (self.open_button, self.folder_button, self.copy_button):
            button.setEnabled(enabled)
        count = self.thumbnails.count()
        self.previous_button.setEnabled(count > 1)
        self.next_button.setEnabled(count > 1)

    def previous_image(self) -> None:
        count = self.thumbnails.count()
        if count:
            self.thumbnails.setCurrentRow((self.thumbnails.currentRow() - 1) % count)

    def next_image(self) -> None:
        count = self.thumbnails.count()
        if count:
            self.thumbnails.setCurrentRow((self.thumbnails.currentRow() + 1) % count)

    def open_current_image(self) -> None:
        if self._current_path and self._current_path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._current_path)))

    def open_current_folder(self) -> None:
        if self._current_path and self._current_path.parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._current_path.parent)))

    def copy_current_path(self) -> None:
        if self._current_path:
            QApplication.clipboard().setText(str(self._current_path))
            self.status_message.emit("图片路径已复制。")

    @staticmethod
    def _thumbnail_icon(path: Path) -> QIcon:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            size.scale(QSize(104, 104), Qt.KeepAspectRatio)
            reader.setScaledSize(size)
        image = reader.read()
        return QIcon(QPixmap.fromImage(image)) if not image.isNull() else QIcon()


class HistoryGalleryDialog(QDialog):
    """Independent, searchable browser for every image under the configured root."""

    def __init__(self, repository: SQLiteRepository, output_root: Callable[[], Path], parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.output_root = output_root
        self.batches: list[GalleryBatch] = []
        self._visible: list[tuple[Path, GalleryBatch]] = []
        self._current_path: Path | None = None
        self._current_batch: GalleryBatch | None = None
        self.setWindowTitle("ANIMA 全部生成图片画廊")
        self.resize(1280, 820)

        outer = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search_edit = QLineEdit(); self.search_edit.setPlaceholderText("搜索项目、文件名或提示词")
        self.project_combo = QComboBox(); self.model_combo = QComboBox(); self.batch_combo = QComboBox()
        self.project_combo.setMinimumWidth(150); self.model_combo.setMinimumWidth(150); self.batch_combo.setMinimumWidth(250)
        refresh_button = QPushButton("刷新全部图片"); refresh_button.clicked.connect(self.refresh)
        filters.addWidget(QLabel("搜索")); filters.addWidget(self.search_edit, 1)
        filters.addWidget(QLabel("项目")); filters.addWidget(self.project_combo)
        filters.addWidget(QLabel("模型")); filters.addWidget(self.model_combo)
        filters.addWidget(QLabel("批次")); filters.addWidget(self.batch_combo)
        filters.addWidget(refresh_button)
        outer.addLayout(filters)

        split = QSplitter(Qt.Horizontal)
        left = QWidget(); left_layout = QVBoxLayout(left); left_layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("正在读取历史图片…"); left_layout.addWidget(self.summary)
        self.thumbnails = QListWidget()
        self.thumbnails.setViewMode(QListWidget.IconMode); self.thumbnails.setWrapping(True)
        self.thumbnails.setMovement(QListWidget.Static); self.thumbnails.setResizeMode(QListWidget.Adjust)
        self.thumbnails.setIconSize(QSize(150, 150)); self.thumbnails.setGridSize(QSize(178, 184))
        self.thumbnails.currentRowChanged.connect(self._image_changed)
        self.thumbnails.itemDoubleClicked.connect(lambda _item: self.open_current_image())
        left_layout.addWidget(self.thumbnails, 1); split.addWidget(left)

        right = QWidget(); right_layout = QVBoxLayout(right); right_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = PreviewLabel(); self.preview.setMinimumSize(480, 480)
        self.preview.double_clicked.connect(self.open_current_image); right_layout.addWidget(self.preview, 1)
        actions = QHBoxLayout()
        previous = QPushButton("← 上一张"); previous.clicked.connect(self.previous_image)
        next_button = QPushButton("下一张 →"); next_button.clicked.connect(self.next_image)
        open_button = QPushButton("查看原图"); open_button.clicked.connect(self.open_current_image)
        folder_button = QPushButton("打开所在文件夹"); folder_button.clicked.connect(self.open_current_folder)
        copy_button = QPushButton("复制路径"); copy_button.clicked.connect(self.copy_current_path)
        for button in (previous, next_button, open_button, folder_button, copy_button): actions.addWidget(button)
        actions.addStretch(); right_layout.addLayout(actions)
        self.details = QTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(150)
        right_layout.addWidget(self.details); split.addWidget(right)
        split.setSizes([610, 650]); outer.addWidget(split, 1)

        self.search_edit.textChanged.connect(self._apply_filters)
        self.project_combo.currentIndexChanged.connect(self._apply_filters)
        self.model_combo.currentIndexChanged.connect(self._apply_filters)
        self.batch_combo.currentIndexChanged.connect(self._apply_filters)

    def refresh(self) -> None:
        project = self.project_combo.currentData()
        model = self.model_combo.currentData()
        batch = self.batch_combo.currentData()
        self.batches = load_gallery_batches(self.repository, self.output_root(), limit=500)
        self._fill_filter(self.project_combo, "全部项目", sorted({item.project_name for item in self.batches}), project)
        self._fill_filter(self.model_combo, "全部模型", sorted({item.model_profile_id for item in self.batches if item.model_profile_id}), model)
        self.batch_combo.blockSignals(True); self.batch_combo.clear(); self.batch_combo.addItem("全部批次", "")
        for item in self.batches: self.batch_combo.addItem(item.title, item.run_id)
        index = self.batch_combo.findData(batch); self.batch_combo.setCurrentIndex(index if index >= 0 else 0)
        self.batch_combo.blockSignals(False)
        self._apply_filters()

    @staticmethod
    def _fill_filter(combo: QComboBox, all_label: str, values: list[str], selected) -> None:
        combo.blockSignals(True); combo.clear(); combo.addItem(all_label, "")
        for value in values: combo.addItem(value, value)
        index = combo.findData(selected); combo.setCurrentIndex(index if index >= 0 else 0); combo.blockSignals(False)

    def _apply_filters(self) -> None:
        query = self.search_edit.text().strip().casefold()
        project = self.project_combo.currentData() or ""
        model = self.model_combo.currentData() or ""
        run_id = self.batch_combo.currentData() or ""
        visible: list[tuple[Path, GalleryBatch]] = []
        for batch in self.batches:
            if project and batch.project_name != project: continue
            if model and batch.model_profile_id != model: continue
            if run_id and batch.run_id != run_id: continue
            for path in batch.image_paths:
                haystack = " ".join((batch.project_name, batch.model_profile_id, path.name, batch.positive_prompt)).casefold()
                if not query or query in haystack: visible.append((path, batch))
        self._visible = visible
        self.thumbnails.blockSignals(True); self.thumbnails.clear()
        for path, batch in visible:
            item = QListWidgetItem(ImageGalleryWidget._thumbnail_icon(path), path.name)
            item.setData(Qt.UserRole, str(path)); item.setToolTip(f"{batch.project_name}\n{path}")
            self.thumbnails.addItem(item)
        self.thumbnails.blockSignals(False)
        self.summary.setText(f"共 {len(visible)} 张图片 · {len(self.batches)} 个生成批次")
        if visible:
            self.thumbnails.setCurrentRow(0); self._image_changed(0)
        else:
            self._image_changed(-1)

    def _image_changed(self, row: int) -> None:
        if not (0 <= row < len(self._visible)):
            self._current_path = None; self._current_batch = None
            self.preview.set_image(None); self.details.clear(); return
        self._current_path, self._current_batch = self._visible[row]
        self.preview.set_image(self._current_path)
        batch = self._current_batch; params = batch.parameters
        reader = QImageReader(str(self._current_path)); size = reader.size()
        width = params.get("width") or (size.width() if size.isValid() else "?")
        height = params.get("height") or (size.height() if size.isValid() else "?")
        parameter_line = " · ".join(value for value in (
            batch.model_profile_id,
            f"{width}×{height}",
            f"Steps {params.get('steps')}" if params.get("steps") is not None else "",
            f"CFG {params.get('cfg')}" if params.get("cfg") is not None else "",
            f"Seed {params.get('seed')}" if params.get("seed") is not None else "",
        ) if value)
        self.details.setPlainText("\n".join(filter(None, (
            f"{batch.project_name} · {batch.created_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
            self._current_path.name,
            parameter_line,
            batch.positive_prompt,
            str(self._current_path),
        ))))

    def previous_image(self) -> None:
        if self.thumbnails.count(): self.thumbnails.setCurrentRow((self.thumbnails.currentRow() - 1) % self.thumbnails.count())

    def next_image(self) -> None:
        if self.thumbnails.count(): self.thumbnails.setCurrentRow((self.thumbnails.currentRow() + 1) % self.thumbnails.count())

    def open_current_image(self) -> None:
        if self._current_path and self._current_path.is_file(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._current_path)))

    def open_current_folder(self) -> None:
        if self._current_path and self._current_path.parent.is_dir(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._current_path.parent)))

    def copy_current_path(self) -> None:
        if self._current_path: QApplication.clipboard().setText(str(self._current_path))
