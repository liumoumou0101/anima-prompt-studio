import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from anima_prompt_studio.domain.models import ArtistProfile
from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.ui.library_dialog import EntityLibraryDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_applying_artist_card_also_persists_it_across_dialog_reopen(app, tmp_path):
    repository = SQLiteRepository(tmp_path / "artists.db")
    dialog = EntityLibraryDialog(repository, ArtistProfile)
    panel = dialog.panels[ArtistProfile]
    panel.fields["display_name"].setText("ASK")
    panel.fields["canonical_tag"].setText("ask (askzy)")
    panel.fields["output_tag"].setText("@ask (askzy)")
    panel.fields["anima_tested_tag"].setText("@ask (askzy)")
    panel.fields["aliases"].setText("askzy, ask")
    panel.fields["style_keywords"].setText("soft lighting, detailed eyes")

    panel.use_selected()

    saved = repository.list_entities(ArtistProfile)
    assert len(saved) == 1
    assert saved[0].output_tag == "@ask (askzy)"
    assert saved[0].anima_tested_tag == "@ask (askzy)"
    assert saved[0].style_keywords == ["soft lighting", "detailed eyes"]

    reopened = EntityLibraryDialog(repository, ArtistProfile)
    reopened_panel = reopened.panels[ArtistProfile]
    assert len(reopened_panel.entities) == 1
    reopened_panel.list.setCurrentRow(0)
    assert reopened_panel.fields["display_name"].text() == "ASK"
    assert reopened_panel.fields["anima_tested_tag"].text() == "@ask (askzy)"
    reopened.close(); dialog.close(); repository.close()
