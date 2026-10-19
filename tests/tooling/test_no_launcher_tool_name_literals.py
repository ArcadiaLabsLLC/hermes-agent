"""No hermes code names a Launcher tool — the underscore spelling of an entry id.

One-action-layer R10, the sibling of ``test_no_launcher_entry_id_literals.py``. The
Launcher names an entry's agent tool ``appFunctionToolName`` (the id with dots turned
into underscores, launcher ``app_function_projections.dart``); hermes takes that name
from the wire (``AppFunctionEntry.parse``) and never derives one. A ``launcher_<area>_<verb>``
token in hermes source is therefore the same second copy of the catalog the dotted
gate refuses, in the other spelling.

The name rule is typed, not a wider regex. The vendored catalog
(``tests/fixtures/launcher_app_functions_catalog.json``, refreshed by
``scripts/vendor_launcher_catalog.py``) is the enumeration. A token
``launcher_<seg>(_<seg>)+`` is a tool name when it equals a catalog ``name``, OR it
starts with ``launcher_<area>_`` for an area the catalog lists (``id.split(".")[1]``)
— so a verb added inside a known area reds before the next refresh, while
``launcher_client_requests`` (``client`` is no area) and ``launcher_qa_*`` (the QA MCP
server's tools, not the catalog) pass. ``FORK_NAMES`` lists the fork's own module and
symbol names the area rule collides with, each with its reason; a stale entry reds.

The honest limit: hermes alone cannot see a rename or a new AREA the Launcher made
after the last refresh. The fixture carries ``source_commit`` so a report can say how
old the enumeration is; the Launcher's export test reds when its committed export is
stale, and the sync sitting vendors it.

A source walk proves a NEGATIVE, so over-approximation is the safe direction: comments
and docstrings count. Killing mutations (2026-10-19): plant ``launcher_generated_list``
in a fork module docstring -> ``test_no_launcher_tool_name_outside_the_allow_list`` red
naming the path; empty the fixture's entries -> ``test_the_catalog_is_not_empty`` red.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.tooling._launcher_literals import population_texts

pytestmark = pytest.mark.gate

CATALOG = Path(__file__).resolve().parents[1] / "fixtures" / "launcher_app_functions_catalog.json"

#: A candidate: ``launcher`` and at least two underscore segments, not inside a longer
#: word (a leading ``_`` still counts, as in a ``test_launcher_<area>_<verb>`` path).
TOOL_NAME = re.compile(r"(?<![A-Za-z0-9])launcher(?:_[a-z0-9]+){2,}(?![A-Za-z0-9])")

#: Fork-owned names the area rule would flag (``app`` is a catalog area, as in
#: ``launcher.app.about``) -> why each is not a tool name.
FORK_NAMES: dict[str, str] = {
    "launcher_app_functions": "module agent_runtime/launcher_app_functions.py",
    "launcher_app_function_answers": "module agent_runtime/launcher_app_function_answers.py",
    "launcher_app_function_binding": "session-state key in agent_runtime/conversations/worker_app_functions.py",
    "launcher_app_function_discovery": "test file test_launcher_app_function_discovery.py, cited by path in tools/tool_search_downstream.py",
    "launcher_app_function_link": "ContextVar name in agent_runtime/launcher_app_functions.py",
}

#: (path, token) -> why it may be written. Empty: the one live leak was rewritten (R10).
ALLOWED: dict[tuple[str, str], str] = {}


def _catalog() -> list[dict]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))["entries"]


def catalog_names(entries: list[dict]) -> frozenset[str]:
    return frozenset(e["name"] for e in entries)


def catalog_areas(entries: list[dict]) -> frozenset[str]:
    return frozenset(e["id"].split(".")[1] for e in entries)


def _is_tool_name(token: str, names: frozenset[str], areas: frozenset[str]) -> bool:
    return token in names or any(token.startswith(f"launcher_{area}_") for area in areas)


def tool_name_leaks(text: str, names: frozenset[str], areas: frozenset[str]) -> set[str]:
    """The tokens in ``text`` the typed rule calls a Launcher tool name, less ``FORK_NAMES``."""

    return {t for t in TOOL_NAME.findall(text)
            if t not in FORK_NAMES and _is_tool_name(t, names, areas)}


def _found(names: frozenset[str], areas: frozenset[str]) -> set[tuple[str, str]]:
    found = set()
    for path, text in population_texts():
        if "launcher_" in text:
            found.update((path, token) for token in tool_name_leaks(text, names, areas))
    return found


def test_the_catalog_is_not_empty():
    # Positive control: an empty fixture would make every walk green.
    entries = _catalog()
    assert len(entries) >= 5, f"the vendored catalog holds {len(entries)} entries"
    assert len(catalog_areas(entries)) >= 3, f"the catalog names {sorted(catalog_areas(entries))}"


def test_the_pattern_sees_a_tool_name_and_not_a_module():
    entries = _catalog()
    names, areas = catalog_names(entries), catalog_areas(entries)
    assert tool_name_leaks('x = "launcher_generated_list"', names, areas) == {"launcher_generated_list"}
    assert tool_name_leaks("import agent_runtime.launcher_app_functions.py", names, areas) == set()
    assert tool_name_leaks("launcher_client_requests", names, areas) == set()
    assert tool_name_leaks("launcher_qa_open_app_tab", names, areas) == set()
    # an unknown verb inside a known area is still a tool name
    assert tool_name_leaks("launcher_generated_frobnicate", names, areas) == {"launcher_generated_frobnicate"}
    assert tool_name_leaks("mylauncher_generated_list", names, areas) == set()
    # a leading underscore still counts: ``_launcher_generated_list`` names the tool
    assert tool_name_leaks("_launcher_generated_list", names, areas) == {"launcher_generated_list"}


def test_fork_names_still_collide():
    """Every FORK_NAMES entry is still written and still matched by the area rule, so the
    list cannot grow a stale exception that hides a real name later."""

    entries = _catalog()
    names, areas = catalog_names(entries), catalog_areas(entries)
    written = {t for _, text in population_texts() for t in TOOL_NAME.findall(text)}
    stale = sorted(t for t in FORK_NAMES if t not in written or not _is_tool_name(t, names, areas))
    assert not stale, "FORK_NAMES lists a name the tree no longer writes or the rule no longer flags:\n  " + "\n  ".join(stale)
    assert not FORK_NAMES.keys() & names, "a FORK_NAMES entry is now a real catalog tool name"


def test_no_launcher_tool_name_outside_the_allow_list():
    entries = _catalog()
    found = _found(catalog_names(entries), catalog_areas(entries))
    leaks = sorted(f"{path}: {token}" for path, token in found - set(ALLOWED))
    assert not leaks, (
        "hermes names a Launcher tool outside the listed catalog (R10). Read the tool from "
        "launcher.app_functions.list and say it in prose, or — if it is a fork module or "
        "symbol name — add it to FORK_NAMES with its reason:\n  " + "\n  ".join(leaks)
    )
    stale = sorted(f"{path}: {token}" for path, token in set(ALLOWED) - found)
    assert not stale, "ALLOWED names a token the tree no longer writes:\n  " + "\n  ".join(stale)
