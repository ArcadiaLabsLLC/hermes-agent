"""MC-A-HELPERS-APPROVAL-NEVER-REACHES-THE-LEADS-CHAT: a turn running in another process (a dispatched
helper's child) waits on an approval the serve can list and answer.

A REAL second process runs upstream's terminal guard (``check_all_command_guards``) under the fork's
``session_approval_scope``, as a dispatched turn does; this process reads it through
``pending_session_approvals`` (what ``runtime.operator.conversation.approvals`` answers) and answers it
through ``approval_relay.answer_relayed`` (what ``respond_operator_approval`` falls back to). Killing
mutations (recorded in the landing commit): drop ``publish`` from ``session_controls._notify_root`` ->
nothing is listed; drop the ``relayed_approvals`` merge -> nothing is listed; the watcher never
resolving -> the child's command is blocked, not approved.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from agent_runtime import approval_relay
from agent_runtime.session_controls import pending_session_approvals
from tests.waiting import wait_until

ROOT = "persona_chat_personainst_helper_123456abcdef"
CHILD = r"""
import json, sys
from agent_runtime.session_controls import session_approval_scope
from tools.approval import check_all_command_guards
with session_approval_scope(sys.argv[1]):
    print(json.dumps(check_all_command_guards("python -c \"import os\"", "local")), flush=True)
"""


def _child(tmp_path):
    from hermes_constants import get_hermes_home

    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"approvals": {"mode": "manual", "timeout": 60}}), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    return subprocess.Popen([sys.executable, "-c", CHILD, ROOT], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=str(tmp_path))


def test_a_child_turns_approval_is_listed_and_answered_from_this_process(tmp_path):
    child = _child(tmp_path)
    try:
        pending = wait_until(lambda: pending_session_approvals(ROOT), timeout=60)
        (request,) = pending
        assert "import os" in request["command"]
        assert approval_relay.answer_relayed(ROOT, request["id"], "once") is True
        out, err = child.communicate(timeout=60)
    finally:
        if child.poll() is None:
            child.kill()
    result = json.loads(out.strip().splitlines()[-1])
    assert result["approved"] is True, (result, err)
    # Both files leave with the wait; nothing is listed afterwards.
    assert pending_session_approvals(ROOT) == []
    assert approval_relay.answer_relayed(ROOT, request["id"], "once") is False


def test_a_record_whose_writer_is_gone_is_never_listed(tmp_path):
    """Positive control for liveness: the same record, written for a process that has exited."""
    gone = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    folder = approval_relay._session_dir(ROOT)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "abc123.json").write_text(json.dumps({
        "session_id": ROOT, "request_id": "abc123", "command": "x", "description": "y",
        "owner_pid": int(gone.stdout), "owner_started": None, "created_at": 1.0}), encoding="utf-8")
    assert approval_relay.relayed_approvals(ROOT) == []
    assert approval_relay.answer_relayed(ROOT, "abc123", "once") is False
