"""Every fork seam that REBINDS an upstream module attribute names its positive control.

RT-REBIND-SEAMS-NO-POSITIVE-CONTROL. A rebind keeps working only while upstream
still looks the name up through the rebound attribute: ``skill_config_cache``
rebound ``skill_utils._RAW_CONFIG_CACHE``, upstream stopped calling ``clear()``
before an insert (``932b20df09``) and the carry sat inert until a release merge
(deleted in ``ffa9579945``). A test that only asserts the attribute IS rebound
stays green through that. The answer is a positive control that drives
UPSTREAM'S OWN CALLER and must see the fork's object take effect.

What this gate walks (a NEGATIVE guarantee — "no rebind without a registered
control" — so a source walk is the right instrument):

* in every fork production file, an assignment to (or ``setattr`` on) an
  attribute of a name bound by importing an UPSTREAM module;
* in every upstream file, a module-scope ``name = fork_fn(name)  # fork seam``.

Each site must be a key of :data:`CONTROLS`, whose value names the test that
drives upstream's caller; that test must exist. A new rebind with no row is red;
a row whose site is gone is red (shrink with the code).
"""

from __future__ import annotations

import ast
import re
import subprocess

import pytest

from scripts import god_file_probe as probe

pytestmark = pytest.mark.gate

ROOT = probe.ROOT

#: site -> ``test file::test name`` driving upstream's caller through the rebound object.
CONTROLS = {
    "agent_runtime/guardrail_mcp_names.py::tool_guardrails.IDEMPOTENT_TOOL_NAMES": (
        "tests/agent_runtime/test_guardrail_mcp_names_downstream.py"
        "::test_a_replayed_registry_spelled_read_is_blocked_as_no_progress"
    ),
    "hermes_state.py::read_only_db_uri": (
        "tests/hermes_cli/test_sessions_export_unwritable_home_downstream.py"
        "::test_export_reads_a_store_in_an_unwritable_home"
    ),
    "tools/environments/local.py::_find_bash": (
        "tests/tools/test_bash_resolution_memo.py::test_upstreams_own_caller_reaches_the_memo"
    ),
}

_UPSTREAM_REBIND = re.compile(r"^([A-Za-z_]\w*) = [A-Za-z_][\w.]*\(\1\)\s*#\s*fork seam")


def _is_upstream_module(dotted: str, upstream: frozenset[str]) -> bool:
    base = dotted.replace(".", "/")
    return f"{base}.py" in upstream or f"{base}/__init__.py" in upstream


def _upstream_module_names(tree: ast.Module, upstream: frozenset[str]) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_upstream_module(alias.name, upstream):
                    names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                if _is_upstream_module(f"{node.module}.{alias.name}", upstream):
                    names.add(alias.asname or alias.name)
    return names


def _fork_rebinds(path: str, upstream: frozenset[str]) -> set[str]:
    try:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    modules = _upstream_module_names(tree, upstream)
    sites: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "setattr"
              and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id in modules):
            attr = node.args[1].value if isinstance(node.args[1], ast.Constant) else "<dynamic>"
            sites.add(f"{path}::{node.args[0].id}.{attr}")
        for target in targets:
            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id in modules):
                sites.add(f"{path}::{target.value.id}.{target.attr}")
    return sites


def _git_grep(pattern: str) -> dict[str, list[str]]:
    """``path -> matching lines`` over the tracked tree (fast: one ``git grep``, no Python read loop)."""
    out = subprocess.run(["git", "grep", "-nE", pattern, "--", "*.py"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", check=False).stdout
    hits: dict[str, list[str]] = {}
    for row in out.splitlines():
        path, _line, text = row.split(":", 2)
        hits.setdefault(path, []).append(text)
    return hits


def rebind_sites() -> set[str]:
    upstream = probe.upstream_paths()
    fork = set(probe.fork_production_files())
    sites: set[str] = set()
    # Candidate fork files: any line that assigns an attribute or calls setattr (the AST then decides).
    for path in _git_grep(r"^\s*(setattr\(|[A-Za-z_]\w*\.[A-Za-z_]\w*\s*(=|\+=|:))"):
        if path in fork:
            sites |= _fork_rebinds(path, upstream)
    for path, lines in _git_grep(r"# *fork seam").items():
        if path in upstream:
            sites |= {f"{path}::{m.group(1)}" for line in lines if (m := _UPSTREAM_REBIND.match(line))}
    return sites


def test_every_rebind_seam_has_a_registered_positive_control():
    sites = rebind_sites()
    assert sites - CONTROLS.keys() == set(), (
        "a fork seam rebinds an upstream attribute with no positive control: add a test that drives "
        "UPSTREAM'S caller and sees the rebound object take effect, then register it in CONTROLS"
    )
    assert CONTROLS.keys() - sites == set(), "a registered rebind seam is gone: delete its CONTROLS row"


@pytest.mark.parametrize("site", sorted(CONTROLS))
def test_each_registered_control_exists(site):
    file, name = CONTROLS[site].split("::")
    source = (ROOT / file).read_text(encoding="utf-8")
    assert re.search(rf"^def {re.escape(name)}\(", source, re.MULTILINE), CONTROLS[site]
