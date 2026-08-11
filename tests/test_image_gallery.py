import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QDesktopServices, QColor, QImage
from PySide6.QtWidgets import QApplication

from anima_prompt_studio.domain.execution_models import (
    GenerationArtifact,
    GenerationRun,
    GenerationRunState,
)
from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.ui.image_gallery import HistoryGalleryDialog, ImageGalleryWidget, load_gallery_batches
from anima_prompt_studio.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _write_image(path: Path, color: str = "#6b4f9e") -> None:
    image = QImage(96, 64, QImage.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path))


def _completed_run(output_dir: Path, run_id: str = "run-gallery") -> GenerationRun:
    run = GenerationRun(
        id=run_id,
        prompt_job_id="job-gallery",
        remote_profile_id="remote-gallery",
        workflow_profile_id="workflow-gallery",
        state=GenerationRunState.COMPLETED,
        output_dir=str(output_dir),
        request_json={
            "resolved_seed": 42,
            "prompt_job": {
                "project_name": "蘑菇森林",
                "model_profile_id": "anima_base_v1",
                "positive_prompt": "A dark elf gathering mushrooms.",
                "generation_params": {
                    "width": 896,
                    "height": 1152,
                    "steps": 35,
                    "cfg": 4.5,
                    "sampler": "er_sde",
                    "seed": 42,
                },
            },
        },
    )
    run.update_state(GenerationRunState.COMPLETED, "完成", 1.0)
    return run


def _artifact(run: GenerationRun, path: Path, artifact_id: str = "artifact-gallery") -> GenerationArtifact:
    return GenerationArtifact(
        id=artifact_id,
        generation_run_id=run.id,
        remote_filename=path.name,
        local_path=str(path),
        mime_type="image/png",
        download_state="completed",
    )


def test_gallery_loads_database_batches_and_parameter_details(app, tmp_path):
    image_path = tmp_path / "result.png"
    second_path = tmp_path / "result_02.png"
    _write_image(image_path)
    _write_image(second_path, "#9e6b4f")
    repository = SQLiteRepository(tmp_path / "gallery.db")
    run = _completed_run(tmp_path)
    repository.save_generation_run(run)
    repository.save_generation_artifact(_artifact(run, image_path))
    repository.save_generation_artifact(_artifact(run, second_path, "artifact-gallery-2"))
    gallery = ImageGalleryWidget(repository, lambda: tmp_path)

    gallery.refresh(run.id)

    assert gallery.has_images
    assert gallery.batch_combo.currentData() == run.id
    assert gallery.thumbnails.count() == 2
    assert gallery.current_image_path == image_path
    assert "anima_base_v1" in gallery.details.toPlainText()
    assert "Steps 35" in gallery.details.toPlainText()
    assert "Seed 42" in gallery.details.toPlainText()
    gallery.next_image()
    assert gallery.current_image_path == second_path
    gallery.previous_image()
    assert gallery.current_image_path == image_path
    gallery.close(); repository.close()


def test_gallery_recovers_batches_from_manifest_without_database_rows(app, tmp_path):
    output_dir = tmp_path / "旧项目" / "character" / "anima_base_v1" / "2026-08-09" / "120000_old"
    output_dir.mkdir(parents=True)
    image_path = output_dir / "old-result.png"
    _write_image(image_path, "#4f7f63")
    (output_dir / "manifest.json").write_text(json.dumps({
        "generation_run": {"id": "old-run", "created_at": "2026-08-09T12:00:00+08:00"},
        "prompt_job": {
            "model_profile": "anima_base_v1",
            "positive_prompt": "Recovered prompt",
            "width": 896,
            "height": 1152,
            "steps": 35,
            "cfg": 4.5,
            "seed": 7,
        },
        "artifacts": [{"local_path": str(image_path)}],
    }, ensure_ascii=False), encoding="utf-8")
    repository = SQLiteRepository(tmp_path / "empty.db")

    batches = load_gallery_batches(repository, tmp_path)

    assert len(batches) == 1
    assert batches[0].run_id == "old-run"
    assert batches[0].project_name == "旧项目"
    assert batches[0].image_paths == [image_path]
    repository.close()


def test_generation_completion_opens_latest_image_in_main_window(app, tmp_path):
    repository = SQLiteRepository(tmp_path / "main.db")
    window = MainWindow(repository)
    image_path = tmp_path / "latest.png"
    _write_image(image_path)
    run = _completed_run(tmp_path, "latest-run")
    artifact = _artifact(run, image_path, "latest-artifact")

    window._remote_generation_succeeded(run, [artifact])

    assert window.center_tabs.currentWidget() is window.image_gallery
    assert window.image_gallery.batch_combo.currentData() == "latest-run"
    assert window.image_gallery.current_image_path == image_path
    assert window.remote_open_button.isEnabled()
    window.close()


def test_main_window_opens_web_gallery_in_system_browser(app, tmp_path, monkeypatch):
    repository = SQLiteRepository(tmp_path / "web-gallery-main.db")
    window = MainWindow(repository)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)

    window.open_history_gallery()

    assert window._gallery_server is not None and window._gallery_server.running
    assert opened and opened[0].toString().startswith("http://127.0.0.1:")
    assert window._gallery_server.gallery_payload()["assets"] == []
    window.close()


def test_independent_history_gallery_shows_tracked_and_untracked_images(app, tmp_path):
    tracked_dir = tmp_path / "记录项目" / "character" / "anima_base_v1" / "2026-08-09" / "120000_run"
    tracked_dir.mkdir(parents=True)
    tracked_path = tracked_dir / "tracked.png"; _write_image(tracked_path)
    orphan_dir = tmp_path / "散落项目" / "character" / "anima_turbo_v1" / "2026-08-09" / "130000_old"
    orphan_dir.mkdir(parents=True)
    orphan_path = orphan_dir / "orphan.png"; _write_image(orphan_path, "#7f634f")
    repository = SQLiteRepository(tmp_path / "history-gallery.db")
    run = _completed_run(tracked_dir, "tracked-run")
    repository.save_generation_run(run)
    repository.save_generation_artifact(_artifact(run, tracked_path, "tracked-artifact"))
    gallery = HistoryGalleryDialog(repository, lambda: tmp_path)

    gallery.refresh()

    assert gallery.thumbnails.count() == 2
    assert "2 张图片" in gallery.summary.text()
    gallery.project_combo.setCurrentIndex(gallery.project_combo.findData("散落项目"))
    assert gallery.thumbnails.count() == 1
    assert gallery._current_path == orphan_path
    gallery.search_edit.setText("does-not-exist")
    assert gallery.thumbnails.count() == 0
    gallery.close(); repository.close()
