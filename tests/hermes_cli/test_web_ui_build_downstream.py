"""Fork-owned tests moved out of ``tests/hermes_cli/test_web_ui_build.py`` (lane CARRY).

Same names, same bodies; the upstream file is byte-identical to upstream.
"""

from pathlib import Path
from unittest.mock import patch
from hermes_cli.main_web_build import _web_ui_build_needed, _web_ui_stamp_path, _write_web_ui_build_stamp

from tests.hermes_cli.test_web_ui_build import (  # noqa: F401 — upstream names the moved tests use
    _isolated_hermes_home,
    _make_web_dir,
)


class TestWebUIHashFailureIsAccounted:
    """An un-hashable web tree must degrade loudly, never silently.

    ``_compute_web_ui_content_hash`` imports ``pathspec`` (a declared
    dependency) lazily. When that import fails the two stamp entry points used
    to disagree in the worst possible way: the WRITER swallowed the error at
    DEBUG and produced no stamp, and the READER called the hash unguarded and
    raised ``ModuleNotFoundError`` straight out of ``hermes web``. The
    swallowed write was the only thing keeping the reader off its own crash,
    and the visible symptom was a full npm install + Vite build on every boot
    with nothing in the log to explain it.

    These pin the contract in both directions without depending on whether
    ``pathspec`` happens to be installed on the host.
    """

    @staticmethod
    def _root(web_dir: Path) -> Path:
        return web_dir.parent.parent if web_dir.parent.name == "apps" else web_dir.parent

    def test_unwritable_stamp_is_reported_at_warning(self, tmp_path, caplog):
        web_dir, _ = _make_web_dir(tmp_path)
        boom = ModuleNotFoundError("No module named 'pathspec'")
        with caplog.at_level("WARNING", logger="hermes_cli.main"), \
             patch("hermes_cli.main_web_build._compute_web_ui_content_hash", side_effect=boom):
            _write_web_ui_build_stamp(self._root(web_dir), web_dir)

        # Still never fails the build...
        assert not _web_ui_stamp_path().is_file()
        # ...but the permanent-rebuild state is now on the record.
        assert any(
            "rebuilt on every start" in r.getMessage() for r in caplog.records
        ), f"expected a WARNING about the missing stamp, got: {caplog.records}"

    def test_unhashable_tree_reports_stale_instead_of_raising(self, tmp_path, caplog):
        web_dir, dist_dir = _make_web_dir(tmp_path)
        (dist_dir / ".vite").mkdir(parents=True, exist_ok=True)
        (dist_dir / ".vite" / "manifest.json").write_text("{}", encoding="utf-8")
        # A stamp exists — this is the state that used to reach the crash.
        stamp = _web_ui_stamp_path()
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text('{"contentHash": "deadbeef"}', encoding="utf-8")

        boom = ModuleNotFoundError("No module named 'pathspec'")
        with caplog.at_level("WARNING", logger="hermes_cli.main"), \
             patch("hermes_cli.main_web_build._compute_web_ui_content_hash", side_effect=boom):
            needed = _web_ui_build_needed(web_dir)

        assert needed is True
        assert any(
            "staleness check degraded" in r.getMessage() for r in caplog.records
        ), f"expected a WARNING about the degraded check, got: {caplog.records}"
