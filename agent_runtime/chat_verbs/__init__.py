"""The chat verbs the launcher drives on every chat open and first send — ONE implementation, two doors.

``harness persona chat history|delete``, ``harness persona instance create``
and ``harness mission-chat turn-resolve|queue-skill`` (argv) and their
``runtime.*`` twins (the method lane, ``serve_rpc.chat_verbs``) are the same
operations reached two ways. Each module here owns one decision and returns the
verb's ROW — the dict the argv verb prints with ``--json``: ``ok`` true or
false, and on a refusal a typed ``error_kind`` beside the human ``error``. The
argv handler prints it; the method translates it (``serve_rpc.chat_verbs``).

Modules (all ``lanes``): ``history``, ``queue_skill``, ``turn_resolve``,
``delete``, ``instance_create`` (a translation shim through
``mission_chat_door``: its sequence is an argparse handler with CLI-side
coordinator helpers, the ``persona_open_chat`` precedent).

Stores written: through the owning stores only (queued skills, the turn
journal, SessionDB, ``PersonaInstanceStore``, the event log). Never imported
from here: ``hermes_cli``.
"""

from __future__ import annotations

__layer__ = "lanes"
