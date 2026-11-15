"""An act monitor says which of its listed actions its persona's chat cannot reach (row
``RT-LENS-ACT-PERSONA-LACKS-LISTED-TOOLS``, ``agent_runtime/lens/act_tools.py``).

Seen live 2026-11-14: a persona with no file or terminal tools on its chat lane sealed an act monitor that
could then never act. The answer is read from the same chat-lane helpers the turn resolves through.

Killing mutation (red recorded in the row's commit): ``act_tools`` answers every listed action as present
(``missing: []``) -> the lacking-persona test is red.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

from test_lens_exit_door import _monitor, _rpc


def _config(personas: str) -> None:
    home = Path(os.environ["HERMES_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("agent_runtime:\n  personas:\n" + personas, encoding="utf-8")


def _act_monitor(persona_id: str, actions: list[str]) -> dict:
    manifest = copy.deepcopy(_monitor(level="act", persona_id=persona_id))
    manifest["automation"]["actions"] = actions
    _rpc("runtime.lens.create", {"manifest": manifest})
    return _rpc("runtime.lens.get", {"monitor_id": manifest["monitor_id"]})["result"]


def test_a_persona_whose_chat_lacks_the_listed_tools_is_named():
    _config("    qa:\n      display_name: QA\n      role: qa\n")

    answer = _act_monitor("qa", ["write_file", "terminal"])["act_tools"]

    assert answer["persona_id"] == "qa" and sorted(answer["missing"]) == ["terminal", "write_file"]
    assert "chat_lane_restore_toolsets" in answer["restore_hint"]


def test_a_persona_whose_chat_carries_them_lacks_nothing():
    _config("    qa:\n      display_name: QA\n      role: qa\n      chat_lane_restore_toolsets: [file, terminal]\n")

    assert _act_monitor("qa", ["write_file", "terminal"])["act_tools"]["missing"] == []


def test_an_unknown_persona_lacks_everything_and_other_levels_say_nothing():
    _config("    qa:\n      display_name: QA\n      role: qa\n")

    answer = _act_monitor("nobody", ["write_file"])["act_tools"]
    assert answer["missing"] == ["write_file"] and answer["persona_missing"] is True
    _rpc("runtime.lens.create", {"manifest": {**_monitor(), "monitor_id": "plain"}})
    assert _rpc("runtime.lens.get", {"monitor_id": "plain"})["result"]["act_tools"] is None
