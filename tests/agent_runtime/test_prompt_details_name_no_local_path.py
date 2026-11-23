"""A caller below console tier reads an agent's prompt details without where its files live.

Row ``RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-ITS-AGENTS-CONTEXT-FILES`` (review w1122d.12), kept by
``RT-ACCOUNT-ONLY-A-PHONE-ANSWERS-A-PAIRED-COMPUTER-ONLY-AS-ONE-OF-YOUR-OWN`` (review w1122d.15) for the view-only
device (paired ``--tier read``) when the Look and Run chats computers it was written for left.
``runtime.prompt_observability.agent`` is called through the real dispatcher for a placed agent whose
profile holds a ``SOUL.md`` that itself names paths. Below console tier every context file's ``path``
(and a layer's ``source_path``) is null; the file's name, hash, size and its own words stay. The owner's
console, a console device and an account-level computer keep the paths. Every test runs in the
``tests/agent_runtime`` conftest's isolated store root.

Killing mutations (each red seen 2026-11-23, in a scratch tree):

* ``console_operations.prompt_observability_agent``: return the result unprojected, and the view-only test
  finds the SOUL.md path in the view-only device's reply (the console test stays green; the census reddens too);
* ``console_operations._sees_local_paths``: answer ``False`` for every caller, and the console test finds
  no ``path`` (the view-only test's owner control and the field test's owner arm red with it);
* ``console_operations._prompt_details_for_caller``: project with ``_text_without_paths`` instead of
  ``_unchanged``, and the file-words test finds the SOUL.md preview rewritten (the field test too);
* ``console_operations._LOCAL_PATH_FIELDS``: drop ``"source_path"``, and the field test finds the layer's
  path (the census finds the SOUL layer's ``source_path`` too).
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import call_authorization as ca
from agent_runtime import serve_rpc
from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # noqa: F401  (fixtures)

PROMPT_DETAILS = "runtime.prompt_observability.agent"

#: A SOUL.md's own words that name paths: a view-only device reads a file's words, so these are never rewritten.
_SOUL_WORDS = "I keep notes in /srv/notes and C:\\Users\\me\\notes."


def _ask(caller, agent_id: str) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "p", "method": PROMPT_DETAILS,
                                     "params": {"instance_id": agent_id}},
                                    serve_rpc.RpcContext(caller=caller, transport=ca.TRANSPORT_GATEWAY))


def _device(tier: str) -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_DEVICE, connection_key="d-r", transport=ca.TRANSPORT_GATEWAY,
                        device_id="dev_r", device_tier=tier)


@pytest.fixture
def souled_agent(placed_agent):
    """The placed agent, its profile holding a SOUL.md; returns ``(instance id, the SOUL.md path)``."""

    from hermes_cli.profiles import get_profile_dir

    profile = get_profile_dir("qa")
    profile.mkdir(parents=True, exist_ok=True)
    soul = profile / "SOUL.md"
    soul.write_text(_SOUL_WORDS + "\n", encoding="utf-8")
    return placed_agent["persona_instance_id"], str(soul)


def _soul_row(reply: dict) -> dict:
    rows = [row for context in reply["result"]["chat_contexts"] for row in context["context_files"]
            if row["name"] == "SOUL.md"]
    assert rows, reply
    return rows[0]


def test_a_view_only_device_reads_no_context_file_path(souled_agent):
    agent_id, soul_path = souled_agent
    owner = _ask(ca.STDIO_OWNER, agent_id)
    assert _soul_row(owner)["path"] == soul_path  # the positive control
    profile_root = soul_path.rsplit("/", 2)[0]
    for caller in (_device(ca.TIER_READ),):
        reply = _ask(caller, agent_id)
        assert "result" in reply, (caller, reply)
        assert profile_root not in json.dumps(reply), caller
        row = _soul_row(reply)
        assert row["path"] is None, caller
        assert {key: row[key] for key in ("name", "kind", "sha256", "bytes")} == {
            key: _soul_row(owner)[key] for key in ("name", "kind", "sha256", "bytes")}, caller


def test_the_file_keeps_its_own_words(souled_agent):
    agent_id, _ = souled_agent
    owner_preview = _soul_row(_ask(ca.STDIO_OWNER, agent_id))["preview"]
    assert "/srv/notes" in owner_preview  # the positive control
    assert _soul_row(_ask(_device(ca.TIER_READ), agent_id))["preview"] == owner_preview


def test_the_console_keeps_the_context_file_paths(souled_agent):
    agent_id, soul_path = souled_agent
    account = ca.RpcCaller(kind=ca.CALLER_COMPUTER, transport=ca.TRANSPORT_GATEWAY, connection_key="lane-r",
                           computer_id="cmp-r", computer_grant=ca.COMPUTER_GRANT_ACCOUNT)
    for caller in (ca.STDIO_OWNER, _device(ca.TIER_CONSOLE), account):
        reply = _ask(caller, agent_id)
        assert "result" in reply, (caller, reply)
        assert _soul_row(reply)["path"] == soul_path, caller


def test_a_layers_source_path_is_dropped_and_its_file_name_kept():
    from agent_runtime.serve_rpc.console_operations import _prompt_details_for_caller

    layer = {"name": "Persona identity", "source_context_file": "SOUL.md", "source_sha256": "AB",
             "source_path": "/data/user/0/app/files/profiles/base/SOUL.md", "content": "Rules name /etc/x."}
    receipt = {"name": "AGENTS.md", "path": "D:\\work\\AGENTS.md", "preview": "see /srv/y"}
    section = {"chat_contexts": [{"prompt_layers": [layer], "workspace_agents": receipt}]}
    seen = _prompt_details_for_caller(json.loads(json.dumps(section)), _device(ca.TIER_READ))
    context = seen["chat_contexts"][0]
    assert context["prompt_layers"][0] == {**layer, "source_path": None}
    assert context["workspace_agents"] == {**receipt, "path": None}
    assert _prompt_details_for_caller(json.loads(json.dumps(section)), ca.STDIO_OWNER) == section
