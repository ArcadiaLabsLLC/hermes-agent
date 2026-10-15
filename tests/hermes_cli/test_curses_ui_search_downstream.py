"""Fork-owned tests moved out of ``tests/hermes_cli/test_curses_ui_search.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""



def test_radio_item_plain_preserves_segment_text():
    from hermes_cli.curses_ui import radio_item_plain
    assert radio_item_plain("plain") == "plain"
    assert radio_item_plain([("Local ", "dim"), ("model", "yellow")]) == "Local model"
