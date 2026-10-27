"""RT-CORE-CACHE-INPUT-FAMILIES: the turn- and worker-written families no
projection reads are outside the core cache's input closure.

Live 2026-10-20..25: 7 ``reason=fingerprint_mismatch`` misses whose ``diff=``
paths were ``chat_turn_reservations`` 16, ``work/ws_*`` git internals 9,
``chat_turn_settles`` 4, ``realm_sync_state`` 1. The first three are written on
every turn or fetch and read by no snapshot section; the fourth IS read (the
realm rows) and stays.

Two halves: the digest no longer moves for the three (each with a positive
control that a neighbouring INPUT still moves it), and a runtime reader audit —
a real ``build_snapshot`` over a store seeded with all three opens no file in
them, beside a control that the same spy sees the build's real reads.

Named sabotage: drop ``CHAT_TURN_RESERVATIONS_DIRNAME`` (or the settles name)
from ``_EXCLUDED_STORE_ENTRIES``, or ``WORK_DIRNAME`` from
``_EXCLUDED_NESTED_STORE_NAMES`` → the matching digest case reds.

RT-CORE-CACHE-CONVERGENCE-CENSUS (2026-10-27) adds two of the 2026-08-23 chat-turn
sidecar families, ``persona_chat_leases`` and ``mission_chat_steer``, the same way;
the two it KEEPS (``mission_chat_turns``, ``prompt_observability``) are read by
snapshot sections and ride the positive control.
"""

from __future__ import annotations

import builtins
import io
import os
from pathlib import Path

import pytest

from agent_runtime import core_cache, paths
from agent_runtime.store import WorkspaceStore


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _families(ws_id: str) -> dict[str, Path]:
    return {
        "reservations": paths.chat_turn_reservations_dir() / "k.json",
        "settles": paths.chat_turn_settles_dir() / "s.json",
        "work_git": paths.default_brain_dir(ws_id) / ".git" / "FETCH_HEAD",
        "chat_leases": paths.store_root() / paths.PERSONA_CHAT_LEASES_DIRNAME / "root.owner.json",
        "chat_steer": paths.store_root() / paths.MISSION_CHAT_STEER_DIRNAME / "sess" / "active.json",
    }


@pytest.fixture
def seeded(isolate_agent_runtime_root):
    ws = WorkspaceStore().create(name="Families")
    family = _families(ws.id)
    for path in family.values():
        _write(path, "one")
    _write(paths.default_brain_dir(ws.id) / "TODO.md", "- row\n")
    return ws, family


@pytest.mark.parametrize("name", ["reservations", "settles", "work_git", "chat_leases", "chat_steer"])
def test_a_family_write_leaves_the_digest_unchanged(seeded, name):
    _ws, family = seeded
    before = core_cache.build_input_fingerprint()
    assert before is not None
    _write(family[name], "two, and longer")
    _write(family[name].with_name("added.json"), "{}")
    after = core_cache.build_input_fingerprint()
    assert after is not None
    assert after.digest == before.digest, name


@pytest.mark.parametrize(
    "neighbour",
    ["brain_note", "realm_sync_state", "mission_chat_turns", "prompt_observability"],
)
def test_a_neighbouring_input_still_moves_the_digest(seeded, neighbour):
    """Positive control: the exclusions are exactly as wide as audited."""

    ws, _family = seeded
    target = {
        "brain_note": paths.default_brain_dir(ws.id) / "TODO.md",
        "realm_sync_state": paths.store_root() / "realm_sync_state" / "realm_x.json",
        "mission_chat_turns": paths.store_root() / "mission_chat_turns" / "sess.json",
        "prompt_observability": paths.prompt_observability_dir() / "ctx.json",
    }[neighbour]
    before = core_cache.build_input_fingerprint()
    _write(target, "- moved, with more bytes\n")
    after = core_cache.build_input_fingerprint()
    assert after is not None and before is not None
    assert after.digest != before.digest, neighbour


def test_the_snapshot_build_reads_none_of_the_excluded_families(seeded, monkeypatch):
    _ws, family = seeded
    roots = [str(paths.chat_turn_reservations_dir()), str(paths.chat_turn_settles_dir()),
             str(family["work_git"].parent), str(family["chat_leases"].parent),
             str(family["chat_steer"].parent.parent)]
    workspaces = str(paths.store_root() / "workspaces")
    opened: list[str] = []
    real_open = io.open

    def spy(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    real_scandir, real_listdir = os.scandir, os.listdir

    def scandir_spy(path=".", *args, **kwargs):
        opened.append(str(path))
        return real_scandir(path, *args, **kwargs)

    def listdir_spy(path=".", *args, **kwargs):
        opened.append(str(path))
        return real_listdir(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    # A family is READ when a reader lists it too (a glob is how a new file reaches a section).
    monkeypatch.setattr(os, "scandir", scandir_spy)
    monkeypatch.setattr(os, "listdir", listdir_spy)
    from agent_runtime.snapshot import build_snapshot

    build_snapshot(build_info={"caller": "probe"})

    # Positive control: the spy sees a projection INPUT the build reads (the
    # workspace record), not merely the cache's own write-back.
    assert any(path.startswith(workspaces) for path in opened), opened[:20]
    read = [path for path in opened if any(path.startswith(root) for root in roots)]
    assert not read, read
