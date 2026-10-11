"""uv.lock's exclude-newer-package table stays sorted (``scripts/sort_uv_lock_options.py``)."""

from __future__ import annotations

from scripts import sort_uv_lock_options as sorter

UNSORTED = 'version = 1\n\n[options.exclude-newer-package]\nzeta = false\nalpha = false\nmid-pkg = false\n\n[[package]]\nname = "b"\n'


def test_the_committed_lock_table_is_sorted():
    text = sorter.LOCK.read_text(encoding="utf-8")
    assert sorter.TABLE in text
    assert sorter.sort_table(text) == text, "run python scripts/sort_uv_lock_options.py after uv lock"


def test_sort_orders_only_the_table(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_bytes(UNSORTED.encode("utf-8"))
    assert sorter.main(["--check", str(lock)]) == 1
    assert lock.read_bytes() == UNSORTED.encode("utf-8")
    assert sorter.main([str(lock)]) == 0
    assert lock.read_text(encoding="utf-8") == (
        'version = 1\n\n[options.exclude-newer-package]\nalpha = false\nmid-pkg = false\nzeta = false\n\n[[package]]\nname = "b"\n'
    )
    assert sorter.main(["--check", str(lock)]) == 0
