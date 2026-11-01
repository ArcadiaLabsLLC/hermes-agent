"""RT-SLOT-RECEIPTS-IN-PROMPT-CONTEXT: the per-slot context receipts reach the prompt-context row.

Under an assignment the ``--agents-file`` alias is superseded, so ``context_files`` carries no
workspace row at all; the one place the client can read which slot file loaded (``default_choice``)
and why the other did not (``not_default`` / ``missing``) is ``workspace_context_receipt`` — the
same receipt the actor signature folds as ``workspace_agents``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_runtime.persona_slots import DEFAULT_AGENTS_HAS_OWN_CONTENT, _default_file_receipts
from agent_runtime.prompt_observability import load_workspace_agents_context
from agent_runtime.prompt_observability.mission_chat import mission_chat_prompt_observability
from hermes_cli.harness_parts.persona.chat_turn_commit import run as turn_run

PERSONA = SimpleNamespace(id="dev", hermes_profile="dev", display_name="Dev", role="dev")


def _assigned_receipt(slot_dir: Path) -> dict:
    (slot_dir / "AGENTS.md").write_text("# Slot rules\nOwn content, not a pointer.\n", encoding="utf-8")
    (slot_dir / "CLAUDE.md").write_text("# Claude rules\n", encoding="utf-8")
    receipts, _sections = _default_file_receipts("app", slot_dir, load_workspace_agents_context)
    return {"kind": "workspace_context", "source": "assigned_slots", "slots": receipts,
            "primary_slot": "app", "primary_source": "only_slot"}


def _by_file(receipt: dict) -> dict[str, dict]:
    return {item["file"]: item for item in receipt["slots"]}


def test_the_row_carries_each_slot_files_default_choice_and_the_others_reason(tmp_path):
    receipt = _assigned_receipt(tmp_path)

    row = mission_chat_prompt_observability(persona=PERSONA, workspace_receipt=receipt)

    files = _by_file(row["workspace_context_receipt"])
    assert files["AGENTS.md"]["default_choice"] == DEFAULT_AGENTS_HAS_OWN_CONTENT
    assert files["AGENTS.md"]["included"] is True
    assert files["CLAUDE.md"]["status"] == "not_default"
    assert row["workspace_context_receipt"]["source"] == "assigned_slots"
    # No alias row exists under an assignment: context_files cannot be where this lives.
    assert not any(item.get("kind") == "workspace_context" for item in row["context_files"])


def test_the_row_never_carries_a_preview_and_does_not_alias_the_turns_receipt(tmp_path):
    receipt = _assigned_receipt(tmp_path)
    receipt["slots"][0]["preview"] = "file text"

    row = mission_chat_prompt_observability(persona=PERSONA, workspace_receipt=receipt)

    assert all("preview" not in item for item in row["workspace_context_receipt"]["slots"])
    assert "preview" in receipt["slots"][0]  # the turn's own receipt is untouched


def test_a_row_built_off_a_turn_says_none():
    assert mission_chat_prompt_observability(persona=PERSONA)["workspace_context_receipt"] is None


def test_the_turn_hands_its_workspace_receipt_to_the_row(tmp_path, monkeypatch):
    """The join: the turn's built row carries the receipt its turn context composed."""

    receipt = _assigned_receipt(tmp_path)
    monkeypatch.setattr(turn_run, "_turn_skill_resolver", lambda _registries: None)
    commit = SimpleNamespace(
        args=SimpleNamespace(surface_prompt=""), persona=PERSONA, session_id="s1", client_message_id="m1",
        session_db=None, message="hi", model_selection={}, turn_root_registries=None,
    )
    skills = SimpleNamespace(queued=(), required=(), loaded=(), missing=())
    turn_context = SimpleNamespace(
        lane_workspace=SimpleNamespace(id="ws", name="WS"), workspace_agents=None,
        workspace_agents_receipt=receipt, situational_hud={}, situational_hud_revision=None,
        situational_hud_delivery=None, skills=skills,
    )
    instance = SimpleNamespace(id="inst_1", skill_overrides=None)

    row = turn_run._RunPhases._prompt_observability_row(commit, turn_context, instance)

    assert _by_file(row["workspace_context_receipt"])["AGENTS.md"]["default_choice"] == DEFAULT_AGENTS_HAS_OWN_CONTENT
