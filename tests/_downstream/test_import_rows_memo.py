"""``tests/_downstream/import_rows_memo.py``: the closure walk's import rows, kept by content across processes.

Row FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-EMBEDDED-PHONE-SESSION-FILE. A kept row set must never outlive the
bytes it was read from: an edited file is parsed again, whatever its path, size or mtime say.
"""

from __future__ import annotations

import os

from scripts import bundle_profile_closure as closure
from tests._downstream.import_rows_memo import memoized_import_rows


def _rows(path, memo):
    with memoized_import_rows(memo) as counts:
        rows = sorted(row[0] for row in closure._parse_imports(path, "pkg.mod", False))
    return rows, counts


# KILLING MUTATION in the memo's comment (key on the path, not the bytes) -> the edit's stale rows come back.
def test_an_edited_file_is_parsed_again_and_an_unchanged_one_is_not(tmp_path):
    memo = tmp_path / "memo.json"
    source = tmp_path / "mod.py"
    source.write_text("import json\nfrom . import sibling\n", encoding="utf-8")
    stat = source.stat()

    first, counts = _rows(source, memo)
    assert first == ["json", "pkg", "pkg.sibling"] and counts == {"hits": 0, "misses": 1}
    again, counts = _rows(source, memo)
    assert again == first and counts == {"hits": 1, "misses": 0}

    # Same size, same mtime: only the bytes changed.
    source.write_text("import uuid\nfrom . import sibling\n", encoding="utf-8")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert source.stat().st_size == stat.st_size
    edited, counts = _rows(source, memo)
    assert edited == ["pkg", "pkg.sibling", "uuid"] and counts == {"hits": 0, "misses": 1}
    assert closure._parse_imports.__name__ == "_parse_imports" and closure._parse_imports.__module__ == closure.__name__
