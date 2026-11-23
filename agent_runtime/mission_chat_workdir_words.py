"""The words a mission-chat workdir receipt speaks: its rungs, its refusal reasons, its issue code.

Split out of :mod:`agent_runtime.mission_chat_workdir` (a ``stores`` module: it stats the
filesystem) so a lower layer can read the receipt's vocabulary without importing the resolver —
``mission_chat_turns.records`` (``policy``) checks a persisted receipt's ``source`` and issue
``reason`` against these words. The resolver re-exports every name; this module owns none of the
policy, only the spelling.
"""

from __future__ import annotations

__layer__ = "models"

#: ``requirement_failures[].code`` for a configured workdir this machine cannot
#: use. Subject key: ``workdir``.
MISSION_CHAT_WORKDIR_UNRESOLVED = "mission_chat_workdir_unresolved"

#: Where a resolved workdir came from (or why there is none).
WORKDIR_SOURCE_PERSONA_CONFIG = "persona_config"
WORKDIR_SOURCE_PRIMARY_SLOT = "primary_slot"
WORKDIR_SOURCE_WORKSPACE_AGENTS = "workspace_agents_file"
WORKDIR_SOURCE_PERSONA_REPO_SCOPE = "persona_repo_scope"
WORKDIR_SOURCE_CHAT_FOLDER = "chat_folder"
WORKDIR_SOURCE_USER_HOME = "user_home"
WORKDIR_SOURCE_PROCESS_CWD = "process_cwd"
#: A batch lane's worktree (dispatcher plan §2.2, B5): the run names it, it outranks the ladder.
WORKDIR_SOURCE_RUN_OVERRIDE = "run_override"

#: Why a requested path was refused. Typed rather than free text so the
#: transition table is assertable.
WORKDIR_REASON_NOT_ABSOLUTE = "not_absolute"
WORKDIR_REASON_MISSING = "missing"
WORKDIR_REASON_NOT_A_DIRECTORY = "not_a_directory"

#: Every rung a receipt's ``source`` (or an issue row's) may name; the turn record keeps no other word.
WORKDIR_SOURCES = frozenset({
    WORKDIR_SOURCE_PERSONA_CONFIG,
    WORKDIR_SOURCE_PRIMARY_SLOT,
    WORKDIR_SOURCE_WORKSPACE_AGENTS,
    WORKDIR_SOURCE_PERSONA_REPO_SCOPE,
    WORKDIR_SOURCE_CHAT_FOLDER,
    WORKDIR_SOURCE_USER_HOME,
    WORKDIR_SOURCE_PROCESS_CWD,
    WORKDIR_SOURCE_RUN_OVERRIDE,
})
#: Every refusal an issue row's ``reason`` may name.
WORKDIR_REASONS = frozenset({WORKDIR_REASON_NOT_ABSOLUTE, WORKDIR_REASON_MISSING, WORKDIR_REASON_NOT_A_DIRECTORY})

#: The key the turn's receipt (``MissionChatWorkdir.receipt()``) rides under: on the runner's
#: ``result.raw`` (``persona_runtime``) and on the turn's durable record (``chat_turn_commit/settle``,
#: kept by ``mission_chat_turns.records.safe_turn_workdir``). One spelling for both.
TURN_WORKDIR_KEY = "mission_chat_workdir"
