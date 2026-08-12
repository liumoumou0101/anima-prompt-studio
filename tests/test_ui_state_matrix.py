import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QTableWidgetItem

from anima_prompt_studio.domain.execution_models import RemoteCredentials, RemoteProfile, WorkflowProfile
from anima_prompt_studio.domain.models import (
    CharacterSlot, CompositionFieldState, EnhancementItem, GenerationFieldState, ItemState, LoRASelection,
    MatchedTag, PromptJob, SubjectMode,
)
from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.remote.workflow_renderer import WorkflowRenderer
from anima_prompt_studio.services.remote.credential_store import CredentialStore, MemoryCredentialBackend
from anima_prompt_studio.ui.main_window import MainWindow
from anima_prompt_studio.ui.remote_dialogs import build_auto_workflow_profile


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    return existing or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    widget = MainWindow(
        SQLiteRepository(tmp_path / "ui-state.db"),
        CredentialStore(MemoryCredentialBackend()),
    )
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


def test_main_window_switches_to_scrollable_compact_layout(window):
    window.resize(820, 520)
    window._apply_responsive_layout()
    assert window.minimumWidth() <= 820
    assert window.minimumHeight() <= 520
    assert window.main_splitter.orientation() == Qt.Vertical
    assert window.body_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff

    window.resize(1300, 800)
    window._apply_responsive_layout()
    assert window.main_splitter.orientation() == Qt.Horizontal


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


def test_composition_ui_distinguishes_recalculation_from_alternatives(window):
    assert window.recalculate_composition_button.text() == "重新计算"
    assert window.alternative_composition_button.text() == "换一种构图"
    window.job = PromptJob(original_zh="看镜头的天使从天而降", normalized_zh="看镜头的天使从天而降")
    window._load_job_into_ui(); window.recommend_composition()
    best = (window.job.composition.shot, window.job.composition.camera_height, window.job.composition.angle)
    window.recommend_alternative_composition()
    alternative = (window.job.composition.shot, window.job.composition.camera_height, window.job.composition.angle)
    assert alternative != best
    assert window.job.composition.gaze == "看镜头"


def test_mouse_wheel_does_not_change_cfg_or_mark_it_manual(window):
    window.job = PromptJob(model_profile_id="anima_turbo_v1")
    window.pipeline.compiler.apply_model_defaults(window.job); window._load_job_into_ui()
    event = QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, -120),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )
    QApplication.sendEvent(window.cfg, event)
    assert window.cfg.value() == 1.0
    assert window.job.generation_params.cfg == 1.0
    assert window.parameter_state_boxes["cfg"].currentData() == GenerationFieldState.AUTO.value


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


def test_enhancement_tab_explains_quality_terms_when_no_context_rule_matches(window):
    window.job = PromptJob(
        original_zh="一个白发精灵女孩站着",
        normalized_zh="一个白发精灵女孩站着",
        translated_en="A white-haired elf girl standing.",
        quality_profile_id="portrait_detail",
    )
    window.pipeline.recompile(window.job)
    window._refresh_results()

    assert window.enhancement_table.rowCount() == 0
    assert window.enhancement_table.isHidden()
    assert not window.enhancement_empty_label.isHidden()
    assert "精致人物" in window.quality_enhancement_summary.text()
    assert "detailed eyes" in window.quality_enhancement_summary.text()
    assert "detailed eyes" in window.job.positive_prompt
    assert window.center_tabs.tabText(window.enhancement_tab_index) == "增强内容 (0)"


def test_translate_button_populates_context_enhancement_tab(window):
    window.chinese.setPlainText("一个女孩坐在窗边")

    window.translate_and_compile()

    assert window.enhancement_table.rowCount() >= 1
    assert not window.enhancement_table.isHidden()
    assert window.enhancement_empty_label.isHidden()
    ids = {item.id for item in window.job.enhancements}
    assert "window_soft_light" in ids
    assert window.center_tabs.tabText(window.enhancement_tab_index).startswith("增强内容 (")


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


def test_reducing_and_restoring_people_count_preserves_hidden_slots(window):
    window.job = PromptJob(
        original_zh="三个人", normalized_zh="三个人", translated_en="Three people.",
        subject_mode=SubjectMode.CHARACTER,
        character_slots=[
            CharacterSlot(display_name="A"),
            CharacterSlot(display_name="B"),
            CharacterSlot(display_name="C"),
        ],
    )
    window.job.composition.people_count = 3
    window.pipeline.compiler.compile(window.job); window._load_job_into_ui()

    window.people_count.setValue(1)
    assert [slot.display_name for slot in window.job.character_slots] == ["A", "B", "C"]
    assert [item["display_name"] for item in window.job.task_package()["characters"]] == ["A"]

    window.people_count.setValue(3)
    assert [window.slot_table.item(row, 1).text() for row in range(3)] == ["A", "B", "C"]


def test_remote_connection_can_be_entered_and_saved_directly_in_main_window(window):
    window._clear_remote_form()
    window._set_combo_data(window.remote_provider_combo, "custom")
    window.remote_name_edit.setText("测试 4090")
    window.remote_host_edit.setText("gpu.example.com")
    window.remote_port_spin.setValue(22022)
    window.remote_user_edit.setText("ubuntu")
    window._set_combo_data(window.remote_auth_combo, "agent")
    window.remote_comfy_host_edit.setText("127.0.0.1")
    window.remote_comfy_port_spin.setValue(8188)
    window.remote_model_file_edit.setText("anima-turbo.safetensors")

    profile = window._save_remote_profile_from_form(True)

    assert profile.ssh_host == "gpu.example.com"
    assert profile.ssh_port == 22022
    assert profile.ssh_user == "ubuntu"
    assert profile.auth_type.value == "agent"
    assert profile.provider_preset_id == "custom"
    assert profile.model_aliases["anima_turbo_v1"] == "anima-turbo.safetensors"
    assert window.repository.get_remote_profile(profile.id).display_name == "测试 4090"


def test_changing_direct_ssh_endpoint_clears_saved_host_fingerprint(window):
    window._clear_remote_form()
    window.remote_host_edit.setText("old.example.com")
    window.remote_user_edit.setText("root")
    profile = window._save_remote_profile_from_form(True)
    profile.known_host_fingerprint = "SHA256:old"
    window.repository.save_remote_profile(profile)
    window._refresh_remote_controls(selected_remote_id=profile.id)

    window.remote_host_edit.setText("new.example.com")
    changed = window._save_remote_profile_from_form(True)

    assert changed.known_host_fingerprint == ""


def test_cloud_provider_list_defaults_to_compshare_and_can_switch(window):
    window._clear_remote_form()
    assert window.remote_provider_combo.currentData() == "compshare_container"
    assert window.remote_port_spin.value() == 23
    assert window.remote_user_edit.text() == "root"
    assert window.remote_auth_combo.currentData() == "password"
    assert window.remote_comfy_host_edit.text() == "127.0.0.1"
    assert window.remote_comfy_port_spin.value() == 8188

    window._set_combo_data(window.remote_provider_combo, "compshare_ubuntu")
    assert window.remote_port_spin.value() == 22
    assert window.remote_user_edit.text() == "ubuntu"
    assert window.remote_auth_combo.currentData() == "password"

    window._set_combo_data(window.remote_provider_combo, "custom")
    assert window.remote_port_spin.value() == 22
    assert window.remote_user_edit.text() == "root"
    assert window.remote_auth_combo.currentData() == "private_key"


def test_compshare_login_command_can_be_pasted_and_parsed(window, monkeypatch):
    window._clear_remote_form()
    monkeypatch.setattr(
        QApplication.clipboard(),
        "text",
        lambda: "ssh -p 23 root@203.0.113.10",
    )

    window.paste_and_parse_ssh_command()

    assert window.remote_host_edit.text() == "203.0.113.10"
    assert window.remote_port_spin.value() == 23
    assert window.remote_user_edit.text() == "root"


def test_quick_connection_uses_two_visible_inputs_and_saves_automatically(window, monkeypatch):
    window._clear_remote_form()
    window.remote_ssh_command_edit.setText("ssh -p 23 root@203.0.113.10")
    window.remote_password_edit.setText("temporary-password")
    called = []
    monkeypatch.setattr(window, "test_remote_connection", lambda: called.append(True))

    window.connect_remote_quickly()

    assert called == [True]
    assert window.remote_advanced_panel.isHidden()
    saved = window.repository.list_remote_profiles()
    assert len(saved) == 1
    assert saved[0].ssh_host == "203.0.113.10"
    assert "temporary-password" not in saved[0].model_dump_json()
    assert window.credential_store.read_password(saved[0].id) == "temporary-password"

    window.remote_password_edit.clear()
    window._refresh_remote_controls(selected_remote_id=saved[0].id)
    assert window.remote_password_edit.text() == "temporary-password"


def test_startup_auto_connect_uses_last_profile_and_saved_password(window, monkeypatch):
    window._clear_remote_form()
    window.remote_host_edit.setText("gpu.example.com")
    window.remote_user_edit.setText("root")
    window.remote_password_edit.setText("secure-password")
    window.remote_remember_password.setChecked(True)
    window.remote_auto_connect.setChecked(True)
    profile = window._save_remote_profile_from_form(True)
    profile.known_host_fingerprint = "SHA256:known"
    window.repository.save_remote_profile(profile)
    window._refresh_remote_controls(selected_remote_id=profile.id)
    called = []
    monkeypatch.setattr(window, "test_remote_connection", lambda: called.append(profile.id))

    window._auto_connect_last_remote()

    assert called == [profile.id]
    assert window.repository.get_setting("last_remote_profile_id") == profile.id
    assert window.repository.get_setting("remote_auto_connect") is True


def test_v2_keeps_complex_workflows_selectable_but_only_enables_verified_basic_generation(window):
    window.remote_host_edit.setText("gpu.example.com")
    basic = WorkflowProfile(
        id="basic",
        display_name="01 基础文生图",
        api_workflow={},
        bindings={},
        workflow_kind="txt2img_basic",
    )
    complex_workflow = WorkflowProfile(
        id="complex",
        display_name="20 分块放大",
        api_workflow={},
        bindings={},
        workflow_kind="unknown",
    )
    window.repository.save_workflow_profile(basic)
    window.repository.save_workflow_profile(complex_workflow)

    window._refresh_remote_controls(selected_workflow_id="basic")
    assert window.remote_generate_button.isEnabled()
    assert "V2 可直接生成" in window.workflow_profile_combo.currentText()

    window._set_combo_data(window.workflow_profile_combo, "complex")
    assert not window.remote_generate_button.isEnabled()
    assert "下一版本适配" in window.workflow_profile_combo.currentText()
    assert "下一版本" in window.remote_status.text()

    aesthetic = WorkflowProfile(
        id="aesthetic-v11",
        display_name="22 美学文生图 Aesthetic v1.1",
        api_workflow={},
        bindings={},
        workflow_kind="txt2img_basic",
        compatible_model_profiles=["anima_aesthetic_v1"],
    )
    window.repository.save_workflow_profile(aesthetic)
    window._refresh_remote_controls(selected_workflow_id="aesthetic-v11")
    assert window.model_combo.currentData() == "anima_aesthetic_v1"
    assert window.remote_generate_button.isEnabled()


@pytest.mark.parametrize(("workflow_id", "expected_model", "expected_params"), [
    ("01_基础文生图", "anima_base_v1", (35, 4.5, "er_sde")),
    ("02_Turbo极速文生图", "anima_turbo_v1", (10, 1.0, "euler")),
    ("05_DMDX少步文生图", "anima_turbo_v1", (10, 1.0, "euler")),
    ("21_美学文生图_Aesthetic_v1.0", "anima_aesthetic_v1", (35, 4.5, "euler")),
    ("22_美学文生图_Aesthetic_v1.1", "anima_aesthetic_v1", (35, 4.5, "euler")),
])
def test_each_supported_workflow_selection_applies_its_model_defaults(
    window, workflow_id, expected_model, expected_params
):
    profile = WorkflowProfile(
        id=workflow_id,
        display_name=workflow_id,
        api_workflow={},
        bindings={},
        workflow_kind="txt2img_basic",
        source_path=f"/workspace/ComfyUI/user/default/workflows/{workflow_id}.json",
    )
    window.repository.save_workflow_profile(profile)

    window._refresh_remote_controls(selected_workflow_id=workflow_id)

    assert window.model_combo.currentData() == expected_model
    assert (window.steps.value(), window.cfg.value(), window.sampler.text()) == expected_params


def test_workflow_selection_switches_model_preset_and_submission_snapshot(window, monkeypatch, tmp_path):
    workflow = {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": 1, "steps": 10, "cfg": 1.0, "sampler_name": "euler", "scheduler": "normal",
        }},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "anima-base-v1.0.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
        "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI"}},
    }
    profile, missing = build_auto_workflow_profile(workflow, tmp_path / "01_基础文生图.json")
    assert missing == []
    profile.workflow_kind = "txt2img_basic"
    # Simulate a profile saved by the version that did not persist compatibility metadata.
    profile.compatible_model_profiles = []
    profile.source_path = "/workspace/ComfyUI/user/default/workflows/01_基础文生图.json"
    window.repository.save_workflow_profile(profile)

    window.job.translated_en = "A dark elf girl gathering mushrooms."
    window._load_job_into_ui()
    assert window.model_combo.currentData() == "anima_turbo_v1"
    assert (window.steps.value(), window.cfg.value()) == (10, 1.0)

    window._refresh_remote_controls(selected_workflow_id=profile.id)

    assert window.model_combo.currentData() == "anima_base_v1"
    assert window.generation_combo.currentData() == "balanced"
    assert (window.steps.value(), window.cfg.value(), window.sampler.text()) == (35, 4.5, "er_sde")
    assert window.repository.get_workflow_profile(profile.id).compatible_model_profiles == ["anima_base_v1"]
    window.batch.setValue(3)
    assert window.job.generation_params.batch_size == 3

    remote = RemoteProfile(
        ssh_host="gpu.example.invalid",
        ssh_user="root",
        known_host_fingerprint="SHA256:test",
        model_aliases={"anima_base_v1": "anima-base-v1.0.safetensors"},
    )
    launched = []
    monkeypatch.setattr(window, "_selected_remote_profile", lambda: remote)
    monkeypatch.setattr(window, "_request_remote_credentials", lambda _profile: RemoteCredentials(password="test"))
    monkeypatch.setattr(window, "_launch_generation_worker", launched.append)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

    window.generate_remote()

    assert len(launched) == 1
    worker = launched[0]
    assert worker.job.model_profile_id == "anima_base_v1"
    assert worker.job.generation_params.batch_size == 3
    rendered = WorkflowRenderer().render(
        worker.job,
        worker.workflow_profile,
        worker.profile,
        worker.checkpoint_logical_name,
        "full-trigger-test",
    )
    assert rendered.workflow["3"]["inputs"]["steps"] == 35
    assert rendered.workflow["3"]["inputs"]["cfg"] == 4.5
    assert rendered.workflow["3"]["inputs"]["sampler_name"] == "er_sde"
    assert rendered.workflow["4"]["inputs"]["ckpt_name"] == "anima-base-v1.0.safetensors"
    assert rendered.workflow["5"]["inputs"]["batch_size"] == 3
    assert rendered.workflow["7"]["inputs"]["text"]


def test_main_actions_have_visual_hierarchy_and_gallery_menu(window):
    assert window.translate_button.property("buttonRole") == "primary"
    assert window.remote_test_button.property("buttonRole") == "primary"
    assert window.remote_generate_button.property("buttonRole") == "success"
    assert window.remote_cancel_button.property("buttonRole") == "danger"
    assert [action.text() for action in window.menuBar().actions()][:3] == ["文件", "设置", "画廊"]


def test_tag_uncheck_persists_as_exclusion(window):
    window.job.matched_tags = [MatchedTag(tag="hat")]
    window.pipeline.compiler.compile(window.job); window._refresh_results()
    window.tag_table.item(0, 0).setCheckState(Qt.Unchecked)
    assert "hat" in window.job.excluded_tags
    assert "hat" not in {x.tag for x in window.job.matched_tags}
