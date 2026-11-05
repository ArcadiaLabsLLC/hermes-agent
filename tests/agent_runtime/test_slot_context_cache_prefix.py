"""RT-SLOT-CONTEXT-IN-CACHED-PREFIX: a folder slot's context sections ride the cached front of the prompt.

A slot's ``CLAUDE.md`` can be 90 KB (~22k tokens) and loads on EVERY turn (owner ruling 2026-11-01:
never first-turn-only). That costs the cache-read price after the first turn only if the sections sit
in bytes that (a) are identical turn to turn and (b) end at or before an Anthropic cache breakpoint.

These arms run a five-turn chat with two slots assigned through the REAL slot loader
(``mission_chat_turn_context``), the REAL operator system message
(``persona_runtime._mission_chat_surface_message``), the REAL three-tier assembler
(``agent.system_prompt.build_system_prompt_parts``) and the REAL breakpoint planner
(``agent.prompt_caching.apply_anthropic_cache_control``), then replay the request sequence against a
prefix cache: a breakpoint whose whole prefix equals one an earlier turn wrote is a read. Where the
sections sit: in the ``context`` tier, after the static-prefix breakpoint and before the
end-of-system breakpoint, so they are read from cache on turns 2-5 and re-written only on the turn a
file's content changed. What this cannot measure is a provider's own billing; that is a live check.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent.prompt_caching import apply_anthropic_cache_control
from agent.system_prompt import build_system_prompt_parts
from agent_runtime.persona_runtime import _mission_chat_surface_message
from tests.agent_runtime.test_mission_chat_turn_context import _Persona, _slot_build, _slot_instance, _slot_workspace

BACKEND_AGENTS = "# Backend rules\n\n" + "Run the Django checks before landing.\n" * 400
LAUNCHER_CLAUDE = "# Launcher rules\n\n" + "Run the gate before landing.\n" * 1200
LAUNCHER_POINTER = "# Canonical Context\n\n[`CLAUDE.md`](CLAUDE.md) is the canonical agent-context file."


def _agent():
    return SimpleNamespace(
        load_soul_identity=False, skip_context_files=True, valid_tool_names=[], _task_completion_guidance=False,
        _tool_use_enforcement=False, _environment_probe=False, _kanban_worker_guidance="", _memory_store=None,
        _memory_manager=None, model="claude-opus", provider="anthropic", platform="", pass_session_id=False,
        session_id="", _emit_status=lambda *_a, **_k: None)


def _request(instance, history):
    """One turn's planned request: ``(blocks, parts)`` — each block the bytes up to one cache marker."""

    context = _slot_build(instance)
    system = _mission_chat_surface_message(_Persona(), "", workspace_agents_content=context.workspace_agents_content)
    parts = build_system_prompt_parts(_agent(), system_message=system)
    full = "\n\n".join(p for p in parts.values() if p)
    messages = [{"role": "system", "content": full}, *history]
    planned = apply_anthropic_cache_control(messages, native_anthropic=True, static_system_prefix=parts["stable"])
    prefixes, running = [], ""
    for message in planned:
        content = message["content"]
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        for index, block in enumerate(blocks):
            running += message["role"] + "\x00" + block["text"] + "\x01"
            if "cache_control" in block or (index == len(blocks) - 1 and "cache_control" in message):
                prefixes.append(running)
    return prefixes, parts, context


def _chat(tmp_path, *, change_on_turn=None):
    workspace, _roots = _slot_workspace(tmp_path, {
        "backend": {"AGENTS.md": BACKEND_AGENTS},
        "launcher": {"CLAUDE.md": LAUNCHER_CLAUDE, "AGENTS.md": LAUNCHER_POINTER},
    })
    instance = _slot_instance(workspace, ["backend", "launcher"], primary="launcher")
    cache: set[str] = set()
    history: list[dict] = []
    turns = []
    for turn in range(1, 6):
        if turn == change_on_turn:
            (tmp_path / "checkouts" / "launcher" / "CLAUDE.md").write_text(LAUNCHER_CLAUDE + "One new rule.\n",
                                                                         encoding="utf-8")
        history.append({"role": "user", "content": f"turn {turn}"})
        prefixes, parts, context = _request(instance, history)
        read = max((len(p) for p in prefixes if p in cache), default=0)
        cache.update(prefixes)
        turns.append(SimpleNamespace(read=read, written=len(prefixes[-1]) - read, parts=parts, context=context,
                                     prefixes=prefixes))
        history.append({"role": "assistant", "content": f"reply {turn}"})
    return turns


def test_two_slots_sections_sit_before_the_end_of_system_breakpoint_and_after_the_static_one(tmp_path):
    """Mutation: ``build_system_prompt_parts`` puts ``system_message`` in the volatile tier -> red."""

    (first, *_rest) = _chat(tmp_path)
    sections = first.context.workspace_agents_content
    assert "## backend — AGENTS.md" in sections and "## launcher — CLAUDE.md" in sections
    assert sections not in first.parts["stable"] and sections in first.parts["context"]
    static_end, system_end = first.prefixes[0], first.prefixes[1]
    assert sections not in static_end and sections in system_end


def test_turns_two_to_five_read_the_sections_from_cache(tmp_path):
    """Five turns, files unchanged: every turn after the first reads the whole system prompt from cache.

    Mutation: make the slot loader's section text carry the turn (``+ str(time.monotonic())``) -> red.
    """

    turns = _chat(tmp_path)
    system_len = len(turns[0].prefixes[1])
    assert turns[0].read == 0
    assert all(turn.read >= system_len for turn in turns[1:]), [turn.read for turn in turns]
    assert len({turn.prefixes[1] for turn in turns}) == 1  # one system prompt, byte-identical, five turns
    # The resident actor's reuse key carries each file's sha256 (``workspace_agents_receipt``): unchanged
    # files keep one actor, and with it one cached system prompt (``mission_chat_runtime_signature``).
    assert all(turn.context.workspace_agents_receipt == turns[0].context.workspace_agents_receipt for turn in turns)
    # The sections are the bulk of what is read: ~22k tokens on the Eternia repo, here ~14k chars per slot.
    assert len(turns[0].context.workspace_agents_content) > system_len // 2


def test_a_changed_file_breaks_the_cache_on_that_turn_only(tmp_path):
    """Positive control for the arm above: a content change MUST re-write, and only after the static prefix."""

    turns = _chat(tmp_path, change_on_turn=4)
    reads = [turn.read for turn in turns]
    system_len = [len(turn.prefixes[1]) for turn in turns]
    assert reads[3] < system_len[3]  # turn 4 re-writes the system prompt's tail …
    assert reads[3] >= len(turns[3].prefixes[0])  # … but still reads the static prefix in front of the sections
    assert reads[4] >= system_len[4]  # turn 5 reads the new bytes
    assert "One new rule." in turns[3].context.workspace_agents_content
    receipts = [turn.context.workspace_agents_receipt for turn in turns]
    assert receipts[2] != receipts[3] and receipts[3] == receipts[4]  # the reuse key moves once, with the content
