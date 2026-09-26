"""Shared environment-gap fence used by the per-directory test conftests.

`tests/hermes_cli/conftest.py` grew the first copy of this mechanism during the
2026-07-30 mission-lane triage. The 2026-07-31 `upstream/main` sync needed the
same fence in `tests/agent/`, `tests/gateway/` and `tests/tools/`, so the
mechanism lives here once instead of being pasted three more times.

What it is
----------
A probe-backed registry that gives a NAME and a live PROBE to a pre-existing
host/platform gap, and really skips the test while the probe reports the gap.
The older mark-only lane (``_ENV_GAPS`` plus the ``windows_env_gap`` /
``host_dependency_gap`` marks, which left every registered test failing and
only NAMED the gap) was emptied by the 2026-08-10 audits and deleted fork-wide
by lane B5 on 2026-09-25 (program §9 Q30): a lane the registry gate itself
forbade populating was not a reservation.

PROBE-BACKED SKIPS — prefer these (2026-08-10)
----------------------------------------------
The retired mark-only design was built so gaps would stay visible instead of
being quietly skipped. In practice it made ``main`` permanently red, which trained
every reader to treat reds as scenery — and a standing red is the best possible
camouflage. The 2026-08-09 audit of ``tests/tools`` found nine of ten rows were
stale TESTS rather than gaps, and that the red was hiding a real frozen-home
defect. The 2026-08-10 audit of the other three registries found the same shape
again: a 39-row block filed as "Windows home resolution" was a constructor-I/O
defect in ``plugins/platforms/feishu/adapter.py``, a two-row block was a regex
that had drifted out of sync with its own declared sibling, and two host rows
had silently gone stale (the disk they described was no longer full) with
nothing failing to say so.

So a genuine gap registers in ``_ENV_GAP_SKIPS`` with a **live probe**:

    ('test_foo.py', [(lambda: not hasattr(os, "chown"), "os.chown does not "
                      "exist on Windows", {'test_bar'})])

The probe is the honesty mechanism. It is evaluated at collection:

  * probe TRUE  -> the test is really skipped, with the mechanism as the reason,
    so a plain run is GREEN and the gap is visible as a named skip;
  * probe FALSE -> the row does not apply on this host, the test RUNS, and if
    it now passes ``tests/test_env_gap_registry.py`` fails the run and tells
    you to delete the row.

That inverts the failure mode. Under the mark-only design a row went stale
silently and a stale row fences nothing while still reading like a fence. Under
a probe, staleness is a failing test.

A probe must interrogate the MECHANISM, never the platform name.
``not hasattr(os, "chown")`` and ``importlib.util.find_spec("croniter") is
None`` are probes. ``sys.platform == "win32"`` is a probe only when the code
under test itself branches on ``sys.platform`` — i.e. when the platform IS the
mechanism, because the assertion pins a branch the host never selects.

Keeping it honest
-----------------
Any registered node id that PASSES is printed in a
"stale environment-gap registry entries" section at the end of the run, so a
fixed environment — or a fixed test — forces the row to be deleted rather than
quietly masking a future regression. Note this only catches rows that still
RUN; it is the weaker half of the contract, which is why probe-backed skips
above are preferred for anything new.

Rules for adding a row
----------------------
1. Reproduce the failure individually first, and read the traceback to a
   concrete host/platform cause. "It fails on Windows" is not a cause. Do not
   trust an existing row's stated reason either: the 2026-08-10 audit found one
   that blamed cmd.exe for a snippet the code runs under bash on every platform.
2. Prove it is not a regression — run the same node on the pre-merge / pre-change
   ref before registering it.
3. Never register a failure whose cause is a defect in our own code. Fix the
   code. A row here that hides a real bug is worse than a red test.
4. A hang is NOT registrable: the mark deselects at collection time, but a plain
   run still executes the test and the hang kills the whole pytest process,
   taking every other result with it. Hangs need a real prerequisite probe or a
   real fix.
5. A test that asserts a POSIX path SPELLING is not a gap. Windows reproduces
   the behaviour; only the separator, the drive letter or the default codec
   differs. Fix the assertion to pin the guarantee instead of the string.
6. ``monkeypatch.setenv("HOME", ...)`` is not a gap either. ``ntpath.expanduser``
   prefers ``USERPROFILE``, so the reflex silently expands ``~`` to the real
   profile and the test stops testing anything. Use
   ``tests._home_env.point_home_at``.
"""

from __future__ import annotations

from typing import Callable

import pytest

# ── Ownership: a directory's registry may only reach that directory ─────────
#
# Every registry below is keyed by file BASENAME, and every conftest that owns
# one registers ``pytest_collection_modifyitems`` / ``pytest_runtest_logreport``
# — hooks pytest calls GLOBALLY once the conftest is loaded, with every item and
# every report in the session, not just its own directory's. In a single-
# directory run those two facts are invisible. In a combined run
# (``pytest tests/gateway tests/cli``) they compose into a cross-directory
# interaction: one directory's row reaches a same-named file in another
# directory and SKIPS it, or claims its pass as a stale row.
#
# Measured on 2026-09-01 at this HEAD: ``tests/gateway``'s ``_ENV_GAP_SKIPS``
# row for ``test_update_command.py`` also matches ``tests/cli/
# test_update_command.py``. No node id overlaps today, so nothing is currently
# mis-skipped — which is exactly the state a landmine is in before it goes off,
# and a skip that lands this way is silent by construction.
#
# So ownership is a PARAMETER, not a convention: every entry point takes the
# directory whose conftest owns the registry and refuses to touch anything
# outside it. Required, never defaulted — a default is the thing the next
# caller forgets.


def is_owned(path, owner_dir) -> bool:
    """Is ``path`` inside ``owner_dir``? (An unresolvable path is NOT owned.)"""

    from pathlib import Path

    try:
        Path(path).resolve().relative_to(Path(owner_dir).resolve())
    except (ValueError, OSError):
        return False
    return True


def _owner_prefix(registry_location: str) -> str:
    """The node-id prefix a registry's reports must carry, from its location.

    Derived from the location string the tracker is already given
    (``"tests/gateway/conftest.py"`` -> ``"tests/gateway/"``) rather than passed
    separately: two spellings of one directory are two spellings free to drift,
    and this one is already load-bearing (it is printed in the stale-row banner).
    """

    head, _, _ = registry_location.replace("\\", "/").rpartition("/")
    return f"{head}/" if head else ""

# file basename -> [(probe, reason, {node ids within the file}), ...].
#
# ``probe`` is a zero-argument callable returning True when the gap is present
# on THIS host. See the "PROBE-BACKED SKIPS" section of the module docstring:
# the probe is what keeps the row honest, because a row whose probe has gone
# False lets its test run again and ``tests/test_env_gap_registry.py`` fails on
# it.
EnvGapSkipRegistry = dict[str, list[tuple["Callable[[], bool]", str, set[str]]]]


def apply_skips(items, registry: EnvGapSkipRegistry, *, owner_dir) -> None:
    """Skip every registered node whose probe reports the gap is present.

    A row whose probe is False is deliberately left alone: the test runs, and
    a stale row becomes a failing assertion in the registry ledger rather than
    a silent non-fence.

    ``owner_dir`` is the directory whose conftest owns ``registry``; items
    outside it are not this registry's to skip. See the ownership block at the
    top of this module for the combined-run interaction that makes it required.
    """
    for item in items:
        if not is_owned(item.path, owner_dir):
            continue
        groups = registry.get(item.path.name)
        if groups is None:
            continue
        _, _, within_file = item.nodeid.partition("::")
        for probe, reason, node_ids in groups:
            if within_file in node_ids and probe():
                item.add_marker(pytest.mark.skip(reason=reason))


def stale_skip_rows(registry: EnvGapSkipRegistry) -> list[str]:
    """Return ``file::node`` ids whose probe no longer reports a gap.

    Used by ``tests/test_env_gap_registry.py`` to fail the run on a row that
    has stopped describing anything — the enforcement the print-only stale
    tracker never had.

    A verdict about THIS HOST, and only meaningful on a host the registry
    describes. See :func:`firing_skip_rows` for the scope, and the ledger test
    for what is asserted where it does not hold.
    """
    stale: list[str] = []
    for file_name, groups in registry.items():
        for probe, _reason, node_ids in groups:
            if probe():
                continue
            stale.extend(f"{file_name}::{node_id}" for node_id in sorted(node_ids))
    return stale


def firing_skip_rows(registry: EnvGapSkipRegistry) -> list[str]:
    """Return ``file::node`` ids whose probe DOES report the gap on this host.

    The complement of :func:`stale_skip_rows`, and the scope test for it. These
    registries hold gaps measured on a developer host, so a probe answering
    False says "this gap is not present here" — which on a different host is
    the probe working correctly, not a row that rotted. Acting on the stale
    verdict there (delete the row) would drop the fence for the host that DOES
    have the gap.

    So "a host these registries describe" is one where at least one row fires,
    and that is where the stale verdict is issued. The ledger asks it across
    all four registries at once, not per directory — a one-row registry would
    otherwise become unjudgeable the moment its single row went stale.

    The limit, stated rather than discovered: registries holding rows for two
    host classes at once cannot be judged this way, because one firing row puts
    every row of the other class under a verdict it has no standing to receive.
    Measured 2026-09-06 — all 52 rows across the four registries fire on the
    Windows dev box and none fires on the Linux runner (CI run 33969282189
    listed every one of the 52 as stale), so nothing is mixed today. Splitting
    a registry that becomes mixed is the repair.
    """
    firing: list[str] = []
    for file_name, groups in registry.items():
        for probe, _reason, node_ids in groups:
            if not probe():
                continue
            firing.extend(f"{file_name}::{node_id}" for node_id in sorted(node_ids))
    return firing


class KnownDefectTracker:
    """The KNOWN DEFECTS banner: a directory's deliberately-unfenced (or strictly
    xfailed) defects, named at the end of every run that ran them.

    ``record`` takes a report when it is a known defect's CALL-phase outcome and
    it either FAILED or was an xfail (``wasxfail``): a strict ``xfail`` reports as
    ``skipped`` + ``wasxfail``, so a classifier matching ``failed`` alone retires
    the banner the moment the defect is fenced; a strict XPASS arrives as
    ``failed`` with no ``wasxfail`` — the day the row must be deleted. Reports
    outside the owning directory are not this tracker's (``pytest_runtest_logreport``
    is a GLOBAL hook); the owner prefix is derived from ``registry_location``
    exactly as the ownership block above derives it.
    """

    def __init__(self, known: dict[str, str], registry_location: str) -> None:
        self._known = known
        self._owner_prefix = _owner_prefix(registry_location)
        self.failures: list[str] = []

    def record(self, report) -> bool:
        """Feed one report in; True when it was a known defect's (consumed)."""
        if report.when != "call":
            return False
        if not report.nodeid.replace("\\", "/").startswith(self._owner_prefix):
            return False
        file_name = report.nodeid.split("::", 1)[0].rsplit("/", 1)[-1]
        if file_name not in self._known:
            return False
        if report.outcome != "failed" and not hasattr(report, "wasxfail"):
            return False
        self.failures.append(report.nodeid)
        return True

    def report(self, terminalreporter, title: str) -> None:
        """Emit the banner (call from ``pytest_terminal_summary``)."""
        if not self.failures:
            return
        terminalreporter.write_sep("=", title)
        seen: set[str] = set()
        for nodeid in sorted(set(self.failures)):
            file_name = nodeid.split("::", 1)[0].rsplit("/", 1)[-1]
            terminalreporter.write_line(f"  {nodeid}")
            if file_name not in seen:
                seen.add(file_name)
                terminalreporter.write_line(f"  {self._known[file_name]}")
                terminalreporter.write_line("")
