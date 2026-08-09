import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QTableWidgetItem

from anima_prompt_studio.domain.models import (
    CharacterSlot, CompositionFieldState, EnhancementItem, GenerationFieldState, ItemState, LoRASelection,
    MatchedTag, PromptJob, SubjectMode,
)
from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    return existing or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    widget = MainWindow(SQLiteRepository(tmp_path / "ui-state.db"))
    yield widget
    widget.close()


@pytest.mark.parametrize("attribute,widget_name,value", [
    ("shot", "shot", "头像"), ("shot", "shot", "胸像"), ("shot", "shot", "半身"),
    ("shot", "shot", "膝上"), ("shot", "shot", "全身"), ("shot", "shot", "远景"),
    ("camera_height", "camera", "平视"), ("camera_height", "camera", "高机位"), ("camera_height", "camera", "低机位"),
    ("angle", "angle", "正面"), ("angle", "angle", "侧面"), ("angle", "angle", "背面"), ("angle", "angle", "三分之四"),
    ("gaze", "gaze", "看镜头"), ("gaze", "gaze", "看人物"), ("gaze", "gaze", "看物体"), ("gaze", "gaze", "看向画外"),
    ("subject_position", "position", "左"), ("subject_position", "position", "中"), ("subject_position", "position", "右"),
    ("aspect", "aspect", "方形"), ("aspect", "aspect", "竖图"), ("aspect", "aspect", "横图"),
])
def test_every_composition_control_reaches_prompt_job(window, attribute, widget_name, value):
    window._updating = True
    getattr(window, widget_name).setCurrentText(value)
    window._updating = False
    window._sync_ui_to_job()
    assert getattr(window.job.composition, attribute) == value


def test_quality_switch_does_not_reset_composition_ui(window):
    window._updating = True
    window.shot.setCurrentText("全身"); window.camera.setCurrentText("高机位"); window.angle.setCurrentText("侧面")
    window.gaze.setCurrentText("看向画外"); window.position.setCurrentText("左")
    window.quality_combo.setCurrentIndex(window.quality_combo.findData("portrait_detail"))
    window._updating = False; window._sync_ui_to_job()
    values = window.job.composition.model_dump(exclude={"mode", "decisions"})
    assert values == {
        "people_count": 1, "shot": "全身", "camera_height": "高机位", "angle": "侧面",
        "gaze": "看向画外", "aspect": "竖图", "subject_position": "左",
    }


def test_subject_mode_control_round_trips_to_job(window):
    window.subject_mode.setCurrentIndex(window.subject_mode.findData(SubjectMode.SCENE.value))
    window._sync_ui_to_job()
    assert window.job.subject_mode == SubjectMode.SCENE
    window._load_job_into_ui()
    assert window.subject_mode.currentData() == SubjectMode.SCENE.value


def test_model_switch_preserves_ui_composition(window):
    window._updating = True
    window.shot.setCurrentText("全身"); window.camera.setCurrentText("低机位"); window.position.setCurrentText("右")
    window._updating = False; window._sync_ui_to_job()
    window.pipeline.switch_model(window.job, "anima_aesthetic_v1")
    assert window.job.composition.shot == "全身"
    assert window.job.composition.camera_height == "低机位"
    assert window.job.composition.subject_position == "右"


def test_composition_value_change_becomes_user_selected(window):
    window.shot.setCurrentText("全身")
    assert window.job.composition.shot == "全身"
    assert window.job.composition.decision("shot").state == CompositionFieldState.USER_SELECTED
    assert window.composition_state_boxes["shot"].currentData() == "user_selected"


def test_auto_recommendation_updates_ui_and_reason(window):
    window.job = PromptJob(original_zh="一个暗精灵小女孩在森林里采蘑菇", normalized_zh="一个暗精灵小女孩在森林里采蘑菇")
    window._load_job_into_ui(); window.recommend_composition()
    assert window.shot.currentText() == "全身"
    assert window.gaze.currentText() == "看物体"
    assert window.composition_reason_labels["shot"].text()


def test_locked_composition_survives_recommend_and_model_switch(window):
    window.job = PromptJob(original_zh="天使从天而降", normalized_zh="天使从天而降")
    window.job.composition.shot = "胸像"
    window.job.composition.decision("shot").state = CompositionFieldState.LOCKED
    window._load_job_into_ui(); window.recommend_composition()
    window.pipeline.switch_model(window.job, "anima_aesthetic_v1")
    assert window.job.composition.shot == "胸像"
    assert not window.shot.isEnabled()


def test_smart_mode_resets_nonlocked_fields_to_auto(window):
    window.job = PromptJob(original_zh="女孩读书", normalized_zh="女孩读书")
    window.job.composition.shot = "远景"
    window.job.composition.decision("shot").state = CompositionFieldState.USER_SELECTED
    window._load_job_into_ui()
    window.composition_mode.setCurrentIndex(window.composition_mode.findData("smart"))
    assert window.job.composition.decision("shot").state == CompositionFieldState.AUTO
    assert window.job.composition.shot == "半身"


def test_generation_parameter_edit_becomes_manual_and_resets_on_model_switch(window):
    window.steps.setValue(77)
    assert window.job.generation_params.state("steps") == GenerationFieldState.USER_SELECTED
    window.model_combo.setCurrentIndex(window.model_combo.findData("anima_aesthetic_v1"))
    assert window.job.generation_params.steps == 35
    assert window.job.generation_params.state("steps") == GenerationFieldState.AUTO
    assert window.steps.value() == 35


def test_generation_preset_resets_manual_but_preserves_locked(window):
    window.job = PromptJob(model_profile_id="anima_turbo_v1")
    window.pipeline.compiler.apply_model_defaults(window.job)
    window._load_job_into_ui()
    window.steps.setValue(77)
    window.job.generation_params.cfg = 2.5
    window.job.generation_params.set_state("cfg", GenerationFieldState.LOCKED)
    window._load_job_into_ui()
    window.generation_combo.setCurrentIndex(window.generation_combo.findData("quality"))
    assert window.job.generation_params.steps == 12
    assert window.job.generation_params.state("steps") == GenerationFieldState.AUTO
    assert window.job.generation_params.cfg == 2.5
    assert not window.cfg.isEnabled()


@pytest.mark.parametrize("state", [GenerationFieldState.USER_SELECTED, GenerationFieldState.LOCKED])
def test_generation_preset_preserves_ui_dimensions(window, state):
    window.job = PromptJob(model_profile_id="anima_aesthetic_v1")
    window.pipeline.compiler.apply_model_defaults(window.job)
    window.job.generation_params.width = 1024
    window.job.generation_params.height = 1024
    window.job.generation_params.set_state("width", state)
    window.job.generation_params.set_state("height", state)
    window._load_job_into_ui()
    window.generation_combo.setCurrentIndex(window.generation_combo.findData("quality"))
    assert (window.job.generation_params.width, window.job.generation_params.height) == (1024, 1024)
    assert window.job.generation_params.state("width") == state
    assert window.job.generation_params.state("height") == state
    assert (window.width.value(), window.height.value()) == (1024, 1024)


def test_dynamic_composition_preset_updates_dimensions(window):
    window.job = PromptJob(model_profile_id="anima_aesthetic_v1")
    window.pipeline.compiler.apply_model_defaults(window.job)
    window._load_job_into_ui()
    window.composition_preset.setCurrentIndex(window.composition_preset.findData("dynamic_action"))
    window.apply_composition_preset()
    assert window.job.composition.aspect == "横图"
    assert (window.job.generation_params.width, window.job.generation_params.height) == (1152, 896)


def test_enhancement_can_be_disabled_and_edited_in_ui(window):
    window.job.enhancements = [EnhancementItem(id="soft", type="场景", source_rule="window", content="Soft light.")]
    window.pipeline.compiler.compile(window.job); window._refresh_results()
    window.enhancement_table.item(0, 0).setCheckState(Qt.Unchecked)
    window.enhancement_table.item(0, 3).setText("Edited soft light.")
    window.apply_enhancement_changes()
    assert window.job.enhancements[0].enabled is False
    assert window.job.enhancements[0].content == "Edited soft light."


def test_enhancement_lock_is_written_back_from_ui(window):
    window.job.enhancements = [EnhancementItem(id="soft", type="场景", source_rule="window", content="Soft light.")]
    window._refresh_results()
    window.enhancement_table.item(0, 4).setCheckState(Qt.Checked)
    window.apply_enhancement_changes()
    assert window.job.enhancements[0].state.value == "locked"
    assert "Edited soft light" not in window.job.positive_prompt


def test_enhancement_disable_rebuilds_canonical_prose_and_tags(window):
    window.job = PromptJob(
        original_zh="一个女孩坐在窗边", normalized_zh="一个女孩坐在窗边",
        translated_en="A girl sitting by the window.",
    )
    window.pipeline.recompile(window.job); window._refresh_results()
    row = next(row for row, item in enumerate(window.job.enhancements) if item.id == "window_soft_light")
    assert "Soft light falls across her" in window.job.positive_prompt
    window.enhancement_table.item(row, 0).setCheckState(Qt.Unchecked)
    window.apply_enhancement_changes()
    assert "Soft light falls across her" not in window.job.positive_prompt
    assert "soft lighting" not in window.job.positive_prompt.partition("\n\n")[0].split(", ")
    assert next(x for x in window.job.enhancements if x.id == "window_soft_light").enabled is False


def test_enhancement_edit_and_lock_rebuilds_and_survives_recompile(window):
    window.job = PromptJob(
        original_zh="一个女孩坐在窗边", normalized_zh="一个女孩坐在窗边",
        translated_en="A girl sitting by the window.",
    )
    window.pipeline.recompile(window.job); window._refresh_results()
    row = next(row for row, item in enumerate(window.job.enhancements) if item.id == "window_soft_light")
    old = window.enhancement_table.item(row, 3).text()
    replacement = "Warm sunset light falls across her."
    window.enhancement_table.item(row, 3).setText(replacement)
    window.enhancement_table.item(row, 4).setCheckState(Qt.Checked)
    window.apply_enhancement_changes()
    assert replacement in window.job.positive_prompt and old not in window.job.positive_prompt
    item = next(x for x in window.job.enhancements if x.id == "window_soft_light")
    assert item.state == ItemState.LOCKED
    window.pipeline.recompile(window.job)
    assert replacement in window.job.positive_prompt


def test_refresh_results_syncs_scene_people_slots_entities_and_composition(window):
    window.job = PromptJob()
    window.job.semantic_frame.subject_mode = SubjectMode.SCENE
    window.job.composition.people_count = 0
    window.job.composition.angle = "无"; window.job.composition.gaze = "无"; window.job.composition.subject_position = "无"
    window.job.artist_selection = ["@rurudo"]
    window.job.artist_selection_sources = {"@rurudo": "text_derived"}
    window.job.lora_selection = [LoRASelection(logical_id="StyleA", weight=.9, trigger_words=["style a"], source="text_derived")]
    window._refresh_results()
    assert window.people_count.value() == 0 and window.slot_table.rowCount() == 0
    assert window.angle.currentText() == "无" and window.gaze.currentText() == "无" and window.position.currentText() == "无"
    assert window.artists.text() == "@rurudo" and window.loras.text() == "StyleA:0.9:style a"

    window.job.semantic_frame.subject_mode = SubjectMode.CHARACTER
    window.job.composition.people_count = 2
    window.job.character_slots = [CharacterSlot(display_name="A"), CharacterSlot(display_name="B")]
    window._refresh_results()
    assert window.people_count.value() == 2 and window.slot_table.rowCount() == 2
    assert window.slot_table.item(0, 1).text() == "A" and window.slot_table.item(1, 1).text() == "B"


def test_ui_roundtrip_preserves_text_derived_entity_sources(window):
    window.job.artist_selection = ["@rurudo"]
    window.job.artist_selection_sources = {"@rurudo": "text_derived"}
    window.job.lora_selection = [LoRASelection(
        logical_id="StyleA", file_name="StyleA.safetensors", weight=.9,
        trigger_words=["style a"], source="text_derived",
    )]
    window._refresh_results(); window._sync_ui_to_job()
    assert window.job.artist_selection_sources == {"@rurudo": "text_derived"}
    assert window.job.lora_selection[0].source == "text_derived"


def test_people_count_ui_change_immediately_recompiles_prompt_and_export_state(window):
    window.job = PromptJob(
        original_zh="一个女孩站在窗边", normalized_zh="一个女孩站在窗边",
        translated_en="A girl stands by the window.",
    )
    window.pipeline.recompile(window.job); window._load_job_into_ui()
    assert "1girl" in window.job.positive_prompt.partition("\n\n")[0].split(", ")
    window.people_count.setValue(2)
    tags = set(window.job.positive_prompt.partition("\n\n")[0].split(", "))
    assert window.job.composition.people_count == 2 and window.slot_table.rowCount() == 2
    assert "2girls" in tags and not {"1girl", "solo"} & tags
    package = window.job.task_package()
    assert package["composition"]["people_count"] == 2 and "2girls" in package["positive_prompt"]


def test_subject_mode_ui_change_immediately_recompiles_scene(window):
    window.job = PromptJob(
        original_zh="一个女孩站在窗边", normalized_zh="一个女孩站在窗边",
        translated_en="A girl stands by the window.",
        character_slots=[CharacterSlot(display_name="A")],
    )
    window.pipeline.recompile(window.job); window._load_job_into_ui()
    window.subject_mode.setCurrentIndex(window.subject_mode.findData(SubjectMode.SCENE.value))
    tags = set(window.job.positive_prompt.partition("\n\n")[0].split(", "))
    assert window.job.subject_mode == SubjectMode.SCENE
    assert window.job.composition.people_count == 0 and window.slot_table.rowCount() == 0
    assert not {"1girl", "solo", "looking at viewer"} & tags
    assert window.job.task_package()["characters"] == []


def test_slot_edit_immediately_overrides_old_text_attributes(window):
    window.job = PromptJob(
        original_zh="黑发蓝瞳女孩", normalized_zh="黑发蓝瞳女孩",
        translated_en="A girl with black hair and blue eyes.",
        character_slots=[CharacterSlot(appearance_tags=["black hair", "blue eyes"], locked=True)],
    )
    window.pipeline.recompile(window.job); window._load_job_into_ui()
    window.slot_table.item(0, 4).setText("white hair, golden eyes")
    tags = set(window.job.positive_prompt.partition("\n\n")[0].split(", "))
    assert {"white hair", "golden eyes"} <= tags
    assert not {"black hair", "blue eyes"} & tags
    assert window.job.character_slots[0].appearance_tags == ["white hair", "golden eyes"]


def test_scene_sync_and_export_preserve_cached_character_slots(window, tmp_path, monkeypatch):
    window.job = PromptJob(
        original_zh="两个女孩", normalized_zh="两个女孩", translated_en="Two girls.",
        subject_mode=SubjectMode.CHARACTER,
        character_slots=[CharacterSlot(display_name="A"), CharacterSlot(display_name="B")],
    )
    window.job.composition.people_count = 2
    window.pipeline.recompile(window.job, people_count_override=2); window._load_job_into_ui()
    window.subject_mode.setCurrentIndex(window.subject_mode.findData(SubjectMode.SCENE.value))
    assert [x.display_name for x in window.job.character_slots] == ["A", "B"]
    export_path = tmp_path / "scene.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(export_path), "JSON (*.json)"))
    window.export_json()
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["characters"] == []
    assert [x.display_name for x in window.job.character_slots] == ["A", "B"]
    window.subject_mode.setCurrentIndex(window.subject_mode.findData(SubjectMode.CHARACTER.value))
    assert window.slot_table.rowCount() == 2
    assert [window.slot_table.item(row, 1).text() for row in range(2)] == ["A", "B"]
    assert [x.display_name for x in window.job.character_slots] == ["A", "B"]


def test_tag_uncheck_persists_as_exclusion(window):
    window.job.matched_tags = [MatchedTag(tag="hat")]
    window.pipeline.compiler.compile(window.job); window._refresh_results()
    window.tag_table.item(0, 0).setCheckState(Qt.Unchecked)
    assert "hat" in window.job.excluded_tags
    assert "hat" not in {x.tag for x in window.job.matched_tags}
