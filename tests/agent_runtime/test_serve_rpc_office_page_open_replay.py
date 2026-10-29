"""S2 of the page-open write storm: the RPC write handlers ack a content-equal write as a no-op.

Plan ``docs/agent-runtime-harness/planned/office-page-open-write-storm.md`` §3–§5 (T7, T9). The §1.1
measurement as a gate: an office page open re-sends every actor and the folder list it just read;
three such opens leave every revision where the seed left it, append no event, and the serve child's
log names each of those writes ``noop=1``. The positive control is the same lane with one position
moved: it writes, bumps, and logs ``noop=0``.
"""

from __future__ import annotations

import logging
import re

from agent_runtime.events import EventLog
from tests.agent_runtime.office_seed import seed_workspace_record
from tests.agent_runtime.test_serve_rpc_office import SHUTDOWN, _reply, _rpc, _run

WORKSPACE = "ws_rpc_page_open_replay"
PERSONAS = ("alpha", "beta", "gamma")
FOLDERS = ["Agents", "Desks"]
_LOG = "agent_runtime.serve_rpc.protocol"


def _store():
    from agent_runtime.office_store import OfficeStore

    return OfficeStore()


def _payload(persona: str, x: float = 1.0) -> dict:
    return {
        "persona_id": persona,
        "items": [
            {"item_id": persona, "persona_id": persona, "kind": "agent", "position": [x, 2.0], "folder": "Agents"},
            {"item_id": f"desk-{persona}", "persona_id": persona, "kind": "desk", "position": [x, 3.6],
             "folder": "Desks"},
        ],
    }


def _seed() -> dict[str, int]:
    store = _store()
    seed_workspace_record(WORKSPACE)
    store.ensure_surface(WORKSPACE, created_by="seed")
    store.update_surface(WORKSPACE, folders=list(FOLDERS), updated_by="seed")
    for persona in PERSONAS:
        store.upsert_actor(WORKSPACE, _payload(persona), updated_by="seed")
    return _revisions()


def _revisions() -> dict[str, int]:
    store = _store()
    out = {actor.actor_key: actor.revision for actor in store.scan_actors(WORKSPACE).actors}
    out["<surface>"] = store.get_surface(WORKSPACE).revision
    return out


def _events() -> int:
    """The office's events: its domain events and the patches it publishes (a serve's first boot also
    seeds the default realm and workspace, which is not an office write)."""

    return sum(1 for _, event in EventLog().iter_from_offset(0)
               if event.type.startswith("office.") or event.type == "state.patched")


def _open_requests(n: int, revisions: dict[str, int]) -> list[dict]:
    """One page open: every actor re-upserted with the token it was read at, then the folders."""

    requests = [_rpc(f"o{n}-{persona}", "runtime.office.upsert",
                     {"workspace_id": WORKSPACE, "actor": _payload(persona), "expect_revision": revisions[persona],
                      "updated_by": "launcher", "correlation_id": f"open{n}"})
                for persona in PERSONAS]
    requests.append(_rpc(f"o{n}-surface", "runtime.office.surface.update",
                         {"workspace_id": WORKSPACE, "folders": list(FOLDERS),
                          "expect_revision": revisions["<surface>"], "correlation_id": f"open{n}"}))
    return requests


def _write_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOG and r.getMessage().startswith("office_write ")]


def test_t9_three_content_equal_page_opens_write_nothing_and_log_noop(caplog):
    seeded = _seed()
    before = _events()
    caplog.set_level(logging.INFO, logger=_LOG)
    for n in range(3):
        out = _run([*_open_requests(n, seeded), SHUTDOWN])
        for persona in PERSONAS:
            assert _reply(out, f"o{n}-{persona}")["result"] == {
                "actor_key": persona, "revision": seeded[persona], "correlation_id": f"open{n}"}
        assert _reply(out, f"o{n}-surface")["result"]["revision"] == seeded["<surface>"]

    assert _revisions() == seeded
    assert _events() == before
    lines = _write_lines(caplog)
    upserts = [line for line in lines if "op=runtime.office.upsert " in line]
    surfaces = [line for line in lines if "op=runtime.office.surface.update " in line]
    assert len(upserts) == 9 and len(surfaces) == 3
    assert all(re.search(r" noop=1(\s|$)", line) for line in upserts + surfaces), lines


def test_t7_a_moved_actor_on_the_same_lane_writes_and_logs_noop_0(caplog):
    """The positive control: the replay lane is not a lane that never writes."""

    seeded = _seed()
    before = _events()
    caplog.set_level(logging.INFO, logger=_LOG)
    out = _run([_rpc("move", "runtime.office.upsert",
                     {"workspace_id": WORKSPACE, "actor": _payload("alpha", x=5.0),
                      "expect_revision": seeded["alpha"]}), SHUTDOWN])
    assert _reply(out, "move")["result"] == {"actor_key": "alpha", "revision": seeded["alpha"] + 1}
    assert _revisions() == {**seeded, "alpha": seeded["alpha"] + 1}
    assert _events() == before + 2  # state.patched + office.actor.upserted
    (line,) = [line for line in _write_lines(caplog) if "op=runtime.office.upsert " in line]
    assert re.search(r" noop=0(\s|$)", line), line
