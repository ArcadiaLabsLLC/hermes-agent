"""A second seat of an agent wears ``Name · 2`` whichever door placed it.

Row Eternia ``MC-OLD-PLACEMENT-PATH-NAMES-A-SECOND-SEAT-WITH-PARENTHESES`` (owner
2026-11-19: numbered per agent across every workspace; the runtime owns instance names):
the argv ``--add-instance`` doors stored the caller's name verbatim, so Eternia counted
``QA Agent (2)`` itself on that lane. ``PersonaInstanceStore.add_instance`` — the floor
every placing door passes — now numbers the name with ``numbered_instance_name``, so the
caller sends the agent's plain name and reads back the seat's. Driven through the real
argparse tree, the door Eternia's argv lane uses.

MUTATION: return ``display_name`` unchanged from ``PersonaInstanceStore._numbered_seat_name``
and "a second seat … is numbered" reds (seen 2026-11-20: 3 failed). Dropping the clash check
(numbering every name) reds the verbatim-name pins in ``test_persona_assignments.py`` and
``test_serve_rpc_agent_create.py::test_an_explicit_display_name_wins`` (seen: 5 failed).
Dropping the ``default_display_name`` numbering reds "the place numbers a seat it names
itself" (seen: 1 failed).

Since RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT the argv ``--add-instance`` places
through ``runtime.agent.place``'s sequence, which seats in a workspace that exists; the open-chat
door no longer places.
"""

from __future__ import annotations

import json

import pytest

from tests.agent_runtime.office_seed import seed_workspace_record
from tests.hermes_cli.test_placement_id_discriminability import (  # the module's fixtures
    _dispatch,
    hermetic_runtime_root,
    qa_persona,
)


@pytest.fixture(autouse=True)
def workspaces(hermetic_runtime_root):
    from agent_runtime.office_store import OfficeStore

    for workspace in ("ws_a", "ws_b", "ws_c"):
        seed_workspace_record(workspace)
        OfficeStore().ensure_surface(workspace, created_by="seed")


def _add(capsys, name: str | None, workspace: str, *extra: str) -> dict:
    code = _dispatch([
        "harness", "persona", "instance", "create",
        "--persona", "qa",
        "--title", "New operator chat",
        *(["--display-name", name] if name else []),
        "--add-instance",
        "--workspace-id", workspace,
        "--json",
        *extra,
    ])
    data = json.loads(capsys.readouterr().out)
    assert code == 0, data
    return data


def test_a_second_seat_in_another_workspace_is_numbered_with_a_dot(qa_persona, capsys):
    first = _add(capsys, "QA Agent", "ws_a")
    second = _add(capsys, "QA Agent", "ws_b")
    assert first["display_name"] == "QA Agent"
    assert second["display_name"] == "QA Agent · 2"


def test_a_name_no_other_seat_wears_is_kept_as_sent(qa_persona, capsys):
    _add(capsys, "QA Agent", "ws_a")
    assert _add(capsys, "Night shift", "ws_a")["display_name"] == "Night shift"


def test_a_third_seat_takes_the_next_number(qa_persona, capsys):
    _add(capsys, "QA Agent", "ws_a")
    _add(capsys, "QA Agent", "ws_b")
    assert _add(capsys, "QA Agent", "ws_c")["display_name"] == "QA Agent · 3"


def test_the_place_numbers_a_seat_it_names_itself_and_says_so(qa_persona, capsys):
    _add(capsys, "QA Agent", "ws_a")
    assert _add(capsys, None, "ws_b")["display_name"] == "QA Agent · 2"


def test_a_retried_add_keeps_its_own_number(qa_persona, capsys):
    _add(capsys, "QA Agent", "ws_a")
    second = _add(capsys, "QA Agent", "ws_a", "--client-message-id", "cmid-seat-1")
    again = _add(capsys, "QA Agent", "ws_a", "--client-message-id", "cmid-seat-1")
    assert second["persona_instance_id"] == again["persona_instance_id"]
    assert again["display_name"] == "QA Agent · 2"
