"""You can undo an action Lens took (row ``RT-LENS-UNDO-ACTION``, ``agent_runtime/lens/undo.py``).

The act harness (``test_lens_act.py``): each call goes through the real eternia-harness hooks, and the
"tool" itself is the test writing the file between the gate and ``post_tool_call``.

Killing mutations (each red recorded in the row's commit):

* the gate takes no before image (``capture`` answers None) -> every write is "cannot be undone", a proposal;
* ``undo`` restores nothing (the image is never written back) -> the edited file keeps Lens's text;
* ``undo`` keeps a file the action created -> it stays on disk;
* the ``undone_by`` check dropped -> a second undo is not refused.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from test_lens_act import _act, _actions, _forge, hooks  # noqa: F401  (hooks: fixture)
from test_lens_exit_door import _armed, _rpc, door  # noqa: F401  (door: fixture)


def _writes(door, hooks, monkeypatch, *writes):
    """During the turn, each ``(tool, path, text)`` passes the gate, is written, then finishes ok."""

    seen = []

    def during(args):
        import agent_runtime.persona_turn_binding as binding

        agent = SimpleNamespace(_persona_chat_client_message_id=args.client_message_id)
        monkeypatch.setattr(binding, "current_persona_turn_agent", lambda: agent)
        for i, (tool, path, text) in enumerate(writes):
            tool_args = {"path": str(path), "content": text}
            verdict = hooks.refuse_tool_call(tool_name=tool, args=tool_args, tool_call_id=f"call_{i}")
            seen.append(None if verdict is None else verdict["message"])
            if verdict is None:
                Path(path).write_text(text, encoding="utf-8")
                hooks.record_turn_outcome(tool_name=tool, args=tool_args, tool_call_id=f"call_{i}", status="ok")

    door.during = during
    return seen


def test_an_edited_file_and_a_created_file_are_both_undone(door, hooks, guardian, monkeypatch, tmp_path):
    edited, created = tmp_path / "cpu.md", tmp_path / "new.md"
    edited.write_text("before\n", encoding="utf-8")
    _armed(_act())
    seen = _writes(door, hooks, monkeypatch, ("write_file", edited, "lens wrote this\n"),
                   ("write_file", created, "a new note\n"))
    assert _forge().tick() == ["forged"] and seen == [None, None]
    first, second = _actions()
    assert first["undo_handle"] == {"kind": "file", "path": str(edited), "existed": True} and first["undoable"]
    assert second["undo_handle"] == {"kind": "file", "path": str(created), "existed": False}

    answer = _rpc("runtime.lens.undo", {"action_id": first["action_id"]})["result"]
    assert edited.read_text(encoding="utf-8") == "before\n"
    assert answer["action"]["undone_by"] == answer["receipt"]["action_id"]
    receipt = answer["receipt"]
    assert (receipt["tool"], receipt["decided_by"], receipt["result"], receipt["why"], receipt["undoable"]) == (
        "undo", "owner", "ran", "undo", False)

    _rpc("runtime.lens.undo", {"action_id": second["action_id"]})
    assert not created.exists()
    again = _rpc("runtime.lens.undo", {"action_id": first["action_id"]})["error"]
    assert again["data"]["reason"] == "action_already_undone"


def test_what_cannot_be_undone_says_so(door, hooks, guardian, monkeypatch, tmp_path):
    _armed(_act(("write_file", "apply_patch")))
    seen = _writes(door, hooks, monkeypatch, ("write_file", tmp_path, "a directory"))  # no image of a directory
    _forge().tick()

    [proposed] = _actions()
    assert (proposed["result"], proposed["why"], proposed["undo_handle"]) == ("proposed", "cannot_be_undone", None)
    assert seen[0].startswith("Sent to the owner")
    refused = _rpc("runtime.lens.undo", {"action_id": proposed["action_id"]})["error"]
    assert refused["data"]["reason"] == "action_cannot_be_undone"
    missing = _rpc("runtime.lens.undo", {"action_id": "lens-action-unknown"})["error"]
    assert missing["data"]["reason"] == "action_not_found"
