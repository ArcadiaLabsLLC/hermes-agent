"""Every verb a computer below the account grant may call answers it with no absolute local path in a path field.

Row ``RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-ITS-AGENTS-CONTEXT-FILES`` (review w1122d.12): the third
per-verb path fix (``instance_history._for_caller``, ``console_operations._detail_for_caller``, then
``_prompt_details_for_caller``) lands this ONE census over ``registry.computer_reach()``. Each verb is either
CALLED through the real dispatcher as a computer at Run chats (which reaches every Look and Run chats verb) on a
placed agent whose profile holds a ``SOUL.md``, or EXCUSED with the reason it is not read here. A verb that
gains a computer reach and is in neither table reddens the census until it is classified. A called verb must
answer a ``result``, so the census reads a real reply, not a refusal. A leak the census found that is not this
row's one-line pass-through is filed, and its verb sits in ``_FILED`` (exact) until that row lands.

Killing mutations (each red seen 2026-11-23):

* ``console_operations.prompt_observability_agent``: return the result unprojected, and the census finds the
  SOUL.md path under ``context_files[].path`` in ``runtime.prompt_observability.agent``'s reply;
* ``console_operations.instance_detail``: return the result unprojected, and the census finds the profile's
  config path under ``config_path`` in ``runtime.persona.instance.detail``'s reply;
* drop ``runtime.health`` from ``_CALLED``, and the coverage test names it.
"""

from __future__ import annotations

import re

import pytest

from agent_runtime import call_authorization as ca
from agent_runtime import serve_rpc
from agent_runtime.serve_rpc import registry
from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # noqa: F401  (fixtures)

#: An absolute path as a whole value: POSIX, home-relative, a Windows drive or a UNC share.
_ABSOLUTE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\]|\\\\)")
#: A key that names where something lives on disk.
_PATH_KEYS = frozenset({"path", "workdir", "cwd", "runtime_root", "repo_scope", "hermes_home", "home"})
_PATH_SUFFIXES = ("_path", "_dir", "_root", "_home")


def _instance(agent):
    return {"instance_id": agent["persona_instance_id"]}


def _persona_instance(agent):
    return {"persona_instance_id": agent["persona_instance_id"]}


def _no_params(agent):
    return {}


#: Each verb read here, with the params it is called with on the placed agent.
_CALLED = {
    "runtime.agent.directory": _no_params,
    "runtime.agent.files.tree": _persona_instance,
    "runtime.events.after": _no_params,
    "runtime.health": _no_params,
    "runtime.office.get": lambda agent: {"workspace_id": agent["workspace_id"]},
    "runtime.operator.conversation.list": lambda agent: {"install_id": agent["install_id"]},
    "runtime.persona.instance.detail": _instance,
    "runtime.prompt_observability.agent": _instance,
    "runtime.workspace.conversations": _no_params,
}

#: Each verb not read here, and why. A write or a turn is not a read of where files live; a binary reply
#: carries bytes and a media type, no path field; a read that needs a minted handle, a draft, a chat or a
#: live subscription has its own verb test.
_EXCUSED = {
    "runtime.agent.conversation.create": "starts a chat: a write whose receipt is ids",
    "runtime.agent.files.grep": "the files verbs' paths are root-name-prefixed by agent_tree; tree reads them here",
    "runtime.agent.files.read": "the files verbs' paths are root-name-prefixed by agent_tree; tree reads them here",
    "runtime.agent.files.virtual": "asks this device's Eternia, absent in a test",
    "runtime.agent.idle_instances": "ids and display names only (agent_create.staff.idle_instances)",
    "runtime.character.portrait": "a binary portrait",
    "runtime.characters.thumb": "a binary thumbnail of a sprite draft",
    "runtime.chat.message": "runs a turn",
    "runtime.client.capabilities": "declares which namespaces this connection answers; its receipt is their names",
    "runtime.chat.steer": "steers a running turn",
    "runtime.chat.turn.resolve": "resolves a running turn",
    "runtime.media.get": "a binary media fetch by a minted handle",
    "runtime.media.index": "needs a chat's media handles",
    "runtime.office.subscribe": "opens a live subscription; office.get reads the same frame",
    "runtime.office.unsubscribe": "closes a live subscription",
    "runtime.operator.conversation.read": "needs a chat opened under the computer's own scope",
    "runtime.persona.chat.content": "needs a chat transcript",
    "runtime.persona.chat.history": "needs a chat transcript",
    "runtime.persona.chat.history.search": "needs a chat transcript",
    "runtime.persona.instance.open_chat": "starts a chat: a write whose receipt is ids",
    "runtime.profiles.avatar": "a binary avatar",
}


#: Each called verb the census found handing a Look or Run chats computer a local path, with the row that fixes it.
#: Exact, not a ceiling: a verb fixed (or a new leak) reddens the census until this table says so.
_FILED = {
    "runtime.agent.directory": "RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-HERMES-BY-ITS-HEALTH-CHECK-AND-AGENT-LIST",
    "runtime.health": "RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-HERMES-BY-ITS-HEALTH-CHECK-AND-AGENT-LIST",
}


@pytest.fixture
def census_agent(placed_agent):
    """The placed agent, its profile holding a SOUL.md and a config file, so a path has every chance to land."""

    from agent_runtime.store import AgentStore
    from hermes_cli.profiles import get_profile_dir

    profile = get_profile_dir("census")
    profile.mkdir(parents=True, exist_ok=True)
    personas = AgentStore()
    persona = personas.get(placed_agent["persona_id"])
    persona.hermes_profile = "census"
    personas.save(persona)
    (profile / "SOUL.md").write_text("Census soul.\n", encoding="utf-8")
    (profile / "config.yaml").write_text("toolsets:\n  - web\n  - no-such-toolset\n", encoding="utf-8")
    from agent_runtime import paths
    from agent_runtime.gateway_identity import ensure_install_identity
    from agent_runtime.parse_cache import clear_parse_cache
    clear_parse_cache()
    return {**placed_agent, "workspace_id": placed_agent.get("workspace_id") or "ws_open_chat_test",
            "install_id": ensure_install_identity(paths.store_root()).install_id}


def _run_chats_computer() -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_COMPUTER, transport=ca.TRANSPORT_GATEWAY, connection_key="lane-census",
                        computer_id="cmp-census", computer_grant=ca.COMPUTER_GRANT_CHAT)


def _path_fields(node, where=""):
    """Every ``(where, value)`` whose key names a path and whose value is an absolute local path."""

    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{where}.{key}"
            if (key in _PATH_KEYS or key.endswith(_PATH_SUFFIXES)) and isinstance(value, str) and _ABSOLUTE.match(value):
                yield here, value
            yield from _path_fields(value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _path_fields(value, f"{where}[{index}]")


def test_every_verb_a_computer_reaches_is_read_or_excused():
    reach = set(registry.computer_reach())
    assert not set(_CALLED) & set(_EXCUSED)
    assert set(_CALLED) | set(_EXCUSED) == reach, {
        "unclassified": sorted(reach - set(_CALLED) - set(_EXCUSED)),
        "no longer reached": sorted((set(_CALLED) | set(_EXCUSED)) - reach)}


def test_no_called_verb_hands_a_run_chats_computer_a_local_path(census_agent):
    refused, found = {}, {}
    for name, params in sorted(_CALLED.items()):
        reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": name, "method": name, "params": params(census_agent)},
                                         serve_rpc.RpcContext(caller=_run_chats_computer(),
                                                              transport=ca.TRANSPORT_GATEWAY))
        if "result" not in reply:
            refused[name] = reply.get("error")
            continue
        leaks = list(_path_fields(reply["result"]))
        if leaks:
            found[name] = leaks
    assert not refused, refused  # the census reads real replies, not refusals
    assert set(found) == set(_FILED), {name: leaks for name, leaks in found.items() if name not in _FILED} or {
        "fixed, drop from _FILED": sorted(set(_FILED) - set(found))}
