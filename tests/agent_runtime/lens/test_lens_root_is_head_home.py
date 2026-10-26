"""Lens opens the runtime root's head home, never the turn's profile home (RT-LENS-READ-PERSONA-HOME).

Measured live 2026-10-26: a qa turn's ``lens_read`` opened (and created) an empty
``profiles/launcher-qa/lens/lens.sqlite3`` and answered ``monitor_not_found`` for
a monitor ``runtime.lens.latest`` read fine from ``profiles/base/lens``.

Killing mutation (recorded in the landing commit): ``lens_root`` returning
``get_hermes_home() / "lens"`` -> the head-home test reds.
"""

from __future__ import annotations

import json

from agent_runtime.lens import artifacts, credentials, ingress_routes, store
from agent_runtime.lens.tool import handle_lens_read


def _homes(tmp_path, monkeypatch):
    head, turn = tmp_path / "profiles" / "base", tmp_path / "profiles" / "launcher-qa"
    head.mkdir(parents=True)
    turn.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(turn))
    return head, turn


def test_a_turn_under_a_profile_home_reads_the_head_store(tmp_path, monkeypatch):
    head, turn = _homes(tmp_path, monkeypatch)
    monkeypatch.setenv("HERMES_HEAD_HOME", str(head))

    assert store.default_path() == head / "lens" / "lens.sqlite3"
    assert artifacts.episodes_root() == head / "lens" / "episodes"
    assert ingress_routes.ingress_config_path() == head / "lens" / "ingress.json"
    assert credentials.credentials_path() == head.resolve() / "lens" / "credentials.json"

    answer = json.loads(handle_lens_read({"monitor": "w1025a_proof"}))
    assert answer == {"error": "monitor_not_found"}
    assert not (turn / "lens").exists(), "a read under the turn's home must not create a store there"


def test_with_no_head_named_lens_stays_in_the_process_home(tmp_path, monkeypatch):
    """Positive control: the same process, no head authority — the ambient rung
    answers, so an un-headed CLI keeps its own home exactly as before."""

    _head, turn = _homes(tmp_path, monkeypatch)
    monkeypatch.delenv("HERMES_HEAD_HOME", raising=False)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "isolated-root"))

    assert store.default_path() == turn / "lens" / "lens.sqlite3"
