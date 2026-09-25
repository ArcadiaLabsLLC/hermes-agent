"""Full (untrimmed) tool descriptions — fork-owned mirror for T6b details-on-demand.

Context Cost Workstream T6b (2026-07-18). The wire tool schemas ship BRIEF
descriptions (see each tool file); this module preserves the FULL original
description text so ``tool_describe(name)`` can serve it on demand. The brief
rides every API call; the full docs are one ``tool_describe`` call away.

REVERT CONTRACT: this file is intentionally independent of the description-trim
commit. A ``git revert`` of the trims restores the full text to the schemas while
this mirror keeps serving the same originals — the full docs are never lost.

Every tool briefed in ``tools.downstream_schema.BRIEF_DESCRIPTIONS`` has no entry
here: the registry keeps upstream's live text (the brief rides only the wire, via
the eternia-harness ``llm_request`` middleware), so ``full_tool_description``
returns None for it and ``tool_describe`` serves the registry schema — except
``terminal``, still briefed at registration, whose upstream text
``registered_full_description`` captured. Other entries retain the
following snapshot contract.

MIRROR DISCIPLINE: this is a snapshot of the descriptions as they shipped before
the T6b trims. If a tool's genuine documentation changes, update BOTH the brief
schema description and this mirror. Parameter docs are NOT duplicated here —
``tool_describe`` reads live ``parameters`` straight off the registry schema
(the trims never touch parameter schemas).
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Union


def _skill_manage_full() -> str:
    """skill_manage full docs, with the profile-aware skills home resolved live."""
    from hermes_constants import display_hermes_home

    return (
        'Manage skills (create, update, delete). Skills are your procedural memory — reusable approaches for recurring task types. New skills go to \x00HERMES_HOME\x00/skills/; existing skills can be modified wherever they live.\n\nActions: create (full SKILL.md + optional category), patch (old_string/new_string — preferred for fixes), edit (full SKILL.md rewrite — major overhauls only), delete, write_file, remove_file.\n\nOn delete, pass `absorbed_into=<umbrella>` when you\'re merging this skill\'s content into another one, or `absorbed_into=""` when you\'re pruning it with no forwarding target. This lets the curator tell consolidation from pruning without guessing, so downstream consumers (cron jobs that reference the old skill name, etc.) get updated correctly. The target you name in `absorbed_into` must already exist — create/patch the umbrella first, then delete.\n\nCreate when: complex task succeeded (5+ calls), errors overcome, user-corrected approach worked, non-trivial workflow discovered, or user asks you to remember a procedure.\nUpdate when: instructions stale/wrong, OS-specific failures, missing steps or pitfalls found during use. If you used a skill and hit issues not covered by it, patch it immediately.\n\nAfter difficult/iterative tasks, offer to save as a skill. Skip for simple one-offs. Confirm with user before creating/deleting.\n\nGood skills: trigger conditions, numbered steps with exact commands, pitfalls section, verification steps. Use skill_view() to see format examples.\n\nDescription: long descriptions are truncated to the first 57 chars plus \'...\' in the system prompt skill index; longer text is visible via skills_list/skill_view. Keep the trigger self-contained in that first 57-char window: \'Use when <trigger>. <one-line behavior>.\'\n\nPinned skills are protected from deletion only — skill_manage(action=\'delete\') will refuse with a message pointing the user to `hermes curator unpin <name>`. Patches and edits go through on pinned skills so you can still improve them as pitfalls come up; pin only guards against irrecoverable loss.'
    ).replace("\x00HERMES_HOME\x00", display_hermes_home())


FULL_TOOL_DESCRIPTIONS: Dict[str, Union[str, Callable[[], str]]] = {
    "skill_manage": _skill_manage_full,
    'agent_chat_send': (
        "Send a chat message to ANOTHER Harness persona (agent-to-agent chat). Use this when the operator asks you to brief, prompt, deploy, hand off to, or check in with another agent conversationally. The message lands in that persona's own Mission Control chat session and their reply is returned to you. This is conversational only and does not create tracked work. Prefer the persona id (e.g. neko_supervisor, dev, backend_dev, qa), which reaches that persona's canonical primary instance. When a persona runs MORE THAN ONE live instance, pass the specific @personainst_* handle from your Runtime Situation HUD to reach THAT instance exactly. Display names are not accepted.\n\nThread control — threads are TASK-SCOPED (V3, 2026-07-27):\n- OMIT session_id → under the default `new_per_dispatch` policy this MINTS a fresh thread scoped to this task.\n- session_id=<id> → continue THAT exact thread.\n- new_session=false → continue the target's CURRENT default thread.\n- new_session=true → force a fresh thread where the policy would not have opened one. Passing new_session=true together with session_id is contradictory and refused.\nEvery reply carries a `session_established` block {fresh, reason, predecessor_session_id}.\n\nWaiting vs dispatching (2026-08-03):\n- Default (`wait` omitted or true) - you BLOCK on their reply and it comes back in this tool result, on a conversational budget (240s default).\n- `wait=false` - you DISPATCH and keep working. The call returns immediately with a `dispatch_id`; their turn runs in the background on its own longer budget (default 30 min, `agent_runtime.mission_chat.dispatch_max_seconds`); their answer is delivered to you later as a NEW message in this conversation, once you are idle. Use it for anything that takes real time - test suites, builds, long reviews - instead of holding your turn open. The reply is NOT in the wait=false result, so do not re-send because you did not see one.\n- `notify_operator=true` (only meaningful with wait=false) - the delivered turn will instruct you to tell the operator what came back.\n- `agent_chat_dispatches` lists your in-flight and recent background dispatches."
    ),
    'agent_chat_open': (
        "Review the recent message tail of a chat thread with ONE teammate before continuing it — 'what did we last say to each other?', or 'what did that dispatched task actually say?'. Returns the newest messages (role, text, timestamp) of that teammate's CURRENT default thread (threads are task-scoped, so that is the most recently established one), or of a specific session_id you pass (which must belong to that teammate's chat lane — this is not a transcript browser, foreign sessions are refused); name the session_id when you mean an earlier task's thread. Read-only, never creates a session: if you have never chatted with the target, it says so. Prefer the persona id (e.g. dev, qa, neko_supervisor) to review the canonical primary instance's thread; pass a personainst_* handle to review a SPECIFIC instance's thread when a persona runs several. Pair with agent_chat_threads (to find your threads) and agent_chat_send (to reply)."
    ),
    'agent_chat_threads': (
        "List your agent-to-agent chat threads with the teammates on your level (the personas agent_chat_send can reach — the same @personainst_* handles shown in your Runtime Situation HUD). For each teammate: persona id, display name, canonical personainst_* handle, and their CURRENT default thread's session id + title + last activity + message count when one exists. Threads are task-scoped, so that default is the most recently established thread with that teammate, not a stable per-pair thread. A teammate you have never chatted with is listed honestly with no thread yet (no session is created just to answer this). Read-only. Use this to see who you can talk to and which conversations already exist before deciding whether to continue one (agent_chat_send carrying that session_id — an omitted session opens a fresh task thread instead) or review one first (agent_chat_open)."
    ),
    'board_card_add': (
        "Add a planning CARD to the Mission Board (a kanban board scoped to the workspace). Use this to track follow-up work worth remembering. A card is planning state only and never starts tracked work. The card lands in the board's Queued column and is attributed to you. Optional, advisory: only add a card when it is genuinely useful."
    ),
    'process': (
        "Manage background processes started with terminal(background=true). Actions: 'list' (show all), 'poll' (check status + new output), 'log' (full output with pagination), 'wait' (block until done or timeout), 'kill' (terminate), 'write' (send raw stdin data without newline), 'submit' (send data + Enter, for answering prompts), 'close' (close stdin/send EOF)."
    ),
    'skill_view': (
        "Skills allow for loading information about specific tasks and workflows, as well as scripts and templates. Load a skill's full content or access its linked files (references, templates, scripts). First call returns SKILL.md content plus a 'linked_files' dict showing available references/templates/scripts. To access those, call again with file_path parameter."
    ),
    'board_cards': (
        'List the active cards on the Mission Board for the current workspace (or an explicit board_id): title, column, and priority. Read-only. Use it to check what is already tracked before adding a card.'
    ),
    'skill_search': (
        'Search installed skills and the Hermes Skills Hub by query without loading full SKILL.md bodies. Returns compact identifiers/descriptions only; use skill_view for installed matches or hermes skills install for external matches.'
    ),
    'skills_list': (
        'List available skills (name + description). Use skill_search(query) to find matching skills or skill_view(name) to load full content.'
    ),
}


def _current_skill_manage_full() -> str:
    from tools.skill_manager_tool import _skill_manage_description, _display_create_dir
    return _skill_manage_description(_display_create_dir())


# These descriptions follow the new upstream batch/kernel contracts directly.
FULL_TOOL_DESCRIPTIONS.update({
    "skill_manage": _current_skill_manage_full,
})
# Registry names were renamed upstream; the mirrors must follow their live owners.
del FULL_TOOL_DESCRIPTIONS["process"]


def full_tool_description(name: str) -> Optional[str]:
    """Return the full (untrimmed) description for a tool, or None if not mirrored.

    Values may be plain strings or zero-arg callables (for profile-aware text).
    """
    from tools.downstream_schema import BRIEF_DESCRIPTIONS, registered_full_description

    current = registered_full_description(name)
    if current is not None:
        return current
    if name in BRIEF_DESCRIPTIONS:
        # The registry holds upstream's live text; the brief rides only the wire.
        return None
    value = FULL_TOOL_DESCRIPTIONS.get(name)
    if value is None:
        return None
    if callable(value):
        try:
            return value()
        except Exception:
            return None
    return value


__all__ = ["FULL_TOOL_DESCRIPTIONS", "full_tool_description"]
