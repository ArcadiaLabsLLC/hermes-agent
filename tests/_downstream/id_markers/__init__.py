"""Markers the fork applies BY TEST ID to upstream test files it no longer edits.

Lane CARRY (2026-09-24): an upstream test file the fork used to edit in place
(a platform skip, an xfail, a timeout, a fork marker) is restored to upstream's
bytes, and the mark moves here. The file then leaves the ``[up-fp]`` ratchet and
the weekly merge stops conflicting on it.

``ID_MARKS`` maps a node id WITHOUT its parametrize suffix — or one WITH it,
which covers that parameter only, or a class id, which covers every test in the
class, or a bare file path, which covers every test in the file — to the marks
the fork applies. ``_WIN`` / ``_NOT_WIN`` rows are platform treatments; each names what
retires it. A row whose file is collected but whose id no longer exists is a
UsageError, not a silent no-op: an unmatched row would read as coverage it no
longer gives.

**The map** (lane B5, 2026-09-25; the layout sheet is
``docs/agent-runtime-harness/planned/god-file-layout-sheets/id_markers.md``). The rows are
split by the CLASS that RETIRES them -- never by size, never by the lane that filed them --
so the file a lane edits to add a row is data, and its name says what will retire it::

    tests/_downstream/id_markers/
      __init__.py        wiring   this map; re-exports what the readers import by this path
      reasons.py         models   VOCABULARY: _WIN, every reason string, the mark constructors, the shared marks
      fork_marks.py      models   TABLE: fork behaviour on every host -- retired by a fork change / fork PR
      posix_marks.py     models   TABLE (win32): a POSIX premise -- retired by upstream linux_only marks
      upstream_reds.py   models   TABLE (win32): upstream's own Windows reds -- retired by an upstream fix
      distributions.py   models   TABLE: an optional distribution -- retired by installing the extra
      hooks.py           lanes    _merge -> ID_MARKS; the collect / modifyitems / runtest_setup hooks; ids_marked

Following an entry point: a lane adding a row -> the class module (1); "why is this upstream
test xfailed?" -> the reason prefix -> ``reasons`` -> the class module (2); the root plugin's
hook registration (``tests/_downstream/conftest_plugin.py``) -> here -> ``hooks`` (2);
``ids_marked`` -> ``hooks`` (1). Layers go DOWN: here -> ``hooks`` -> the four tables ->
``reasons``. Imports are ABSOLUTE (the tests/_downstream convention). This package is
imported into the ROOT plugin for upstream's whole tree: it never imports ``agent_runtime``.
"""

from __future__ import annotations

from tests._downstream.id_markers.hooks import (
    ID_MARKS,
    ids_marked,
    pytest_collection_modifyitems,
    pytest_make_collect_report,
    pytest_runtest_setup,
)
from tests._downstream.id_markers.distributions import REQUIRES_DISTRIBUTION
from tests._downstream.id_markers.posix_marks import IMPORT_TIME_POSIX_SHIMS
from tests._downstream.id_markers.reasons import (
    NO_LIVE_GATEWAY_MARK,
    TELEGRAM_PARITY_DEFECT_REASON,
)

__layer__ = "wiring"

__all__ = [
    "ID_MARKS",
    "IMPORT_TIME_POSIX_SHIMS",
    "NO_LIVE_GATEWAY_MARK",
    "REQUIRES_DISTRIBUTION",
    "TELEGRAM_PARITY_DEFECT_REASON",
    "ids_marked",
    "pytest_collection_modifyitems",
    "pytest_make_collect_report",
    "pytest_runtest_setup",
]


# ── History: which lane filed which block (relocated banners, lane B5 2026-09-25) ──
# The class modules carry the RETIRING cause per row group; this is the provenance.
#
# ── Lane CARRY2B: upstream test files outside tests/hermes_cli ─────────────
# ── CARRY2B: tests/gateway ──────────────────────────────────────────────────
# ── CARRY2B: agent, hermes_state, plugins, providers, cron, scripts, tui_gateway, tests/*.py
# ── Lane REDS2: the fork-scope gate over the 2026-09-24 wave ───────────────
# ── CARRY3: upstream tests that call monkeypatch.undo() mid-body (see _SCOPED_UNDO).
# ── Lane REDS3: upstream's own Windows reds in byte-identical files, no fork PR
# covers any (X:/wt/_holds/upstream-reds-v2026.9.24.md, classes e-BR and e-ID).
# After the CARRY3 block: a row that already carries a mark keeps it.
# ── Lane REDS3 (wave-close gate on 6251144d09): upstream's own Windows reds that the
# conftest reach now selects. Every id below is red at the tag on this box
# (X:/wt/_holds/upstream-reds-v2026.9.24.md, class in each reason) unless named.
