"""Built-in tag browser data and dialog helpers."""
from pathlib import Path

from anima_prompt_studio.ui.tag_browser_dialog import CATEGORY_LABELS, TagBrowserDialog, category_display


def test_category_display_known_and_unknown():
    assert category_display("clothing") == "服装/配饰"
    assert category_display("no_such_cat") == "no_such_cat"
    assert CATEGORY_LABELS[0][0] == "all"


def test_tag_browser_loads_builtin_tags(qtbot=None):
    # Avoid requiring a running QApplication display when possible.
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication.instance() or QApplication(sys.argv)
    dialog = TagBrowserDialog()
    assert len(dialog.entries) >= 100
    assert dialog.category_combo.count() >= 5
    dialog.search_edit.setText("bikini")
    dialog.refresh_table()
    assert dialog.table.rowCount() >= 1
    # category filter "服装"
    for index in range(dialog.category_combo.count()):
        if dialog.category_combo.itemData(index) == "clothing":
            dialog.category_combo.setCurrentIndex(index)
            break
    dialog.search_edit.clear()
    dialog.refresh_table()
    assert dialog.table.rowCount() >= 10
    _ = app
