"""A chat's first turn records its first byte and waits on no concurrent build (lane h-turn1-again).

Live 2026-10-06 12:04 (local), Neko's new chat, turn ``b00deebf``: the turn ran on the argv
fallback lane without ``--stream`` (the launcher had recycled its connection), so the run handed
the runner no stream callback, the emitter never saw a reply-text delta, and the record carried no
``provider_first_byte`` though the codex stream logged its first substantive progress. Turns 2-4
(``--stream``) recorded it to the millisecond.

The same turn paid 522 ms of ``observability_catalog_walk_ms`` inside its write-ahead span: the
installed-skill catalog memo walked inline on every read past its 15 s TTL, while a snapshot
build was open across the turn (``builds_overlapped=1``). The memo now answers stale and refreshes
off the reader's thread.

Driven through the REAL handler (``_cmd_mission_chat_message``).
"""

from __future__ import annotations

import threading
import time

import pytest

from agent_runtime import snapshot_build_ledger
from agent_runtime.mission_chat_phases import TURN_PHASES_KEY
from agent_runtime.mission_chat_turns import TURN_PROFILE_TIMING_KEY
from agent_runtime.prompt_observability import skills_resolver

from tests.hermes_cli.test_mission_chat_turn_phases import (  # type: ignore
    _drive,
    _record_on_disk,
    _streaming_provider,
    isolate_agent_runtime_root,  # noqa: F401  (re-exported fixture)
    scripted_marks,  # noqa: F401  (re-exported fixture)
)


@pytest.mark.parametrize("stream", [False, True], ids=["argv_no_stream", "streamed"])
def test_a_new_chats_first_turn_records_its_first_byte_on_either_lane(
    monkeypatch, capsys, isolate_agent_runtime_root, scripted_marks, stream  # noqa: F811
):
    """*Killing mutation:* wire ``stream_callback=None`` for a non-``--stream`` turn again --
    the ``argv_no_stream`` case records no ``provider_first_byte``."""

    turn_id = f"turn1_first_byte_{'stream' if stream else 'argv'}"
    _drive(monkeypatch, capsys, _streaming_provider(profile_timing={"resident_actor_reused": 1}),
           turn_id=turn_id, stream=stream)
    record = _record_on_disk(isolate_agent_runtime_root, turn_id)
    phases = record[TURN_PHASES_KEY]

    assert "provider_first_byte" in phases
    assert phases["request_assembled"] <= phases["provider_first_byte"] <= phases["stream_done"]
    # The non-streamed turn gets the stamp and nothing else: no segment element is invented.
    if not stream:
        assert not record.get("elements")


def test_a_first_turn_with_a_concurrent_build_waits_on_no_catalog_walk(
    monkeypatch, capsys, isolate_agent_runtime_root, scripted_marks  # noqa: F811
):
    """A snapshot build is open and its catalog walk is in flight when turn 1 assembles.

    *Killing mutation:* walk inline past the TTL again (no stale answer) -- the turn's own read
    blocks on the gated walk, ``observability_catalog_walk_ms`` reads the wait and
    ``observability_catalog_cached`` reads ``0``.
    """

    from tools import skills_tool

    release = threading.Event()
    walks: list[str] = []

    def gated_walk(**_kwargs):
        walks.append(threading.current_thread().name)
        if len(walks) > 1:  # every walk after the warm one is the slow, in-flight one
            release.wait(3.0)
        return [{"name": "alpha", "description": "", "category": "skills"}]

    monkeypatch.setattr(skills_tool, "_find_all_skills", gated_walk)
    skills_resolver._installed_skill_catalog()  # warm, as the serve's boot leaves it
    skills_resolver._skill_catalog_memo["at"] = time.monotonic() - 60.0  # TTL lapsed

    build = snapshot_build_ledger.begin_build()
    try:
        # The build reads the catalog first: its read starts the one refresh, which blocks.
        snapshot_reader = threading.Thread(
            target=skills_resolver._installed_skill_catalog, daemon=True
        )
        snapshot_reader.start()
        deadline = time.monotonic() + 5.0
        while len(walks) < 2 and time.monotonic() < deadline:  # the build's walk is in flight
            time.sleep(0.01)
        started = time.monotonic()
        _drive(monkeypatch, capsys,
               _streaming_provider(profile_timing={"resident_actor_reused": 1}),
               turn_id="turn1_concurrent_build", stream=False)
        turn_s = time.monotonic() - started
        builds_open = snapshot_build_ledger.builds_in_flight()
        walk_still_in_flight = not release.is_set() and skills_resolver._catalog_refresh["thread"] is not None
    finally:
        release.set()
        refresh = skills_resolver._catalog_refresh["thread"]
        if refresh is not None:
            refresh.join(5)
        snapshot_reader.join(5)
        snapshot_build_ledger.end_build(build)

    record = _record_on_disk(isolate_agent_runtime_root, "turn1_concurrent_build")
    timing = record[TURN_PROFILE_TIMING_KEY]
    assert builds_open == 1  # the build stayed open across the whole turn
    assert timing.get("observability_catalog_cached") == 1, timing
    assert timing.get("observability_catalog_walk_ms") == 0, timing
    assert walk_still_in_flight and turn_s < 3.0
    assert walks[1] == "skill-catalog-refresh"
