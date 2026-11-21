"""The closure walk's per-file import rows, kept on disk by CONTENT for the tests that stage a bundle (fork-owned, test-only).

Row FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-EMBEDDED-PHONE-SESSION-FILE: the ``[phone]`` case of
``tests/agent_runtime/test_embedded_phone_session.py`` stages the phone wheel before its turn, and the
staging re-parses every module the profile reaches (``scripts/bundle_profile_closure.py::_parse_imports``,
~3,300 files): 24.0 s of the case's ~58 s, on every run of every tree. ``_imports`` already keeps the rows
per process, keyed on ``(path, mtime_ns, size, ...)``; this keeps them across processes and worktrees.

A row set is keyed on what it is a function of, and nothing else:

* the file's BYTES (sha256), so an edited file is parsed again however its mtime moved, and an unchanged
  file in a fresh lane tree (new mtimes, same bytes) is a hit;
* the module name and whether it is a package (relative imports resolve against them);
* the target's platform markers (``dead_for_target`` buries branches by them);
* the parser's own source (``scripts/bundle_profile_closure.py``, ``scripts/bundles/closure_platform.py``),
  so a change to how rows are read drops every row.

The memo is one JSON file in the clone's git common directory (shared by every worktree), replaced whole
with the rows the staging read (so it never grows past one staging's files); two writers race to
last-wins, never to a torn file. A missing or unreadable memo is an empty one. Only
:func:`memoized_import_rows` installs it, around one staging; production and every other walk parse as before.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MEMO_NAME = "hermes-closure-import-rows.json"
_PARSER_SOURCES = ("scripts/bundle_profile_closure.py", "scripts/bundles/closure_platform.py")


def default_memo_path() -> Path | None:
    done = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                          capture_output=True, text=True, check=False, timeout=30)
    common = done.stdout.strip()
    return Path(common) / MEMO_NAME if done.returncode == 0 and common else None


def _parser_fingerprint() -> str:
    digest = hashlib.sha256()
    for rel in _PARSER_SOURCES:
        digest.update((REPO / rel).read_bytes())
    return digest.hexdigest()[:16]


def _read(memo: Path) -> dict:
    try:
        data = json.loads(memo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(memo: Path, data: dict) -> None:
    staged = memo.with_name(f"{memo.name}.{os.getpid()}.tmp")
    try:
        staged.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.replace(staged, memo)
    except OSError:
        with contextlib.suppress(OSError):
            staged.unlink()


@contextlib.contextmanager
def memoized_import_rows(memo: Path | None = None):
    """Inside the block, ``bundle_profile_closure._parse_imports`` answers from the memo by content.

    Yields the counts (``hits``, ``misses``) for the caller's own assertions."""
    from scripts import bundle_profile_closure as closure

    memo = memo if memo is not None else default_memo_path()
    counts = {"hits": 0, "misses": 0}
    if memo is None:
        yield counts
        return
    fingerprint = _parser_fingerprint()
    stored = _read(memo)
    rows_by_key = stored.get("rows", {}) if stored.get("parser") == fingerprint else {}
    used: dict[str, list] = {}
    added = False
    real = closure._parse_imports

    def _parse_imports(path: Path, module: str, is_pkg: bool):
        nonlocal added
        platform = [closure.TARGET_ENV.get(k) for k in ("os_name", "sys_platform", "platform_system")]
        try:
            content = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except OSError:
            return real(path, module, is_pkg)
        # MUTATION: key on the path instead of ``content`` and
        # test_an_edited_file_is_parsed_again_and_an_unchanged_one_is_not reddens (the stale rows come back).
        key = json.dumps([content, module, is_pkg, platform])
        rows = rows_by_key.get(key)
        if rows is not None:
            counts["hits"] += 1
            used[key] = rows
            return iter(tuple(row) for row in rows)
        counts["misses"] += 1
        fresh = [list(row) for row in real(path, module, is_pkg)]
        rows_by_key[key] = used[key] = fresh
        added = True
        return iter(tuple(row) for row in fresh)

    closure._parse_imports = _parse_imports
    try:
        yield counts
    finally:
        closure._parse_imports = real
        if added:  # only the rows this staging read: an edited file's old rows leave with it
            _write(memo, {"parser": fingerprint, "rows": used})
