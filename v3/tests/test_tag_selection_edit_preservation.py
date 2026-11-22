"""Saving an unrelated picker edit cannot undo a reviewed manual deletion."""
from anima_prompt_studio_v3.core.manual_tags import sync_tag_selection


def test_new_artist_does_not_restore_manually_deleted_old_character():
    assert sync_tag_selection('a woman in a blue coat', ['shana', '@artist a'], ['shana']) == \
        '@artist a, a woman in a blue coat'


def test_only_new_tags_are_inserted_with_old_manual_deletion_and_removal():
    assert sync_tag_selection('old series, a woman', ['shana', 'new series'], ['shana', 'old series']) == \
        'new series, a woman'
