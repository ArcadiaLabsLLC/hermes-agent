"""What a computer driving a phone at Look or Run chats reaches is stated once, on each verb.

Hermes row ``RT-A-COMPUTERS-REACH-ON-A-PHONE-IS-STATED-ONCE-PER-VERB-AND-CHECKED-AGAINST-WHAT-ETERNIA-CALLS``
(review w1122d.1): each verb's ``@method(name, tier, computer=...)`` names the lowest grant that reaches
it, the dispatcher hands that word to the gate beside the tier, and the manifest publishes it as
``computer_reach``. The refactor widens nothing: the derived sets equal the two hand-kept allowlists as
they stood at hermes 64e7914196 (which already held ``runtime.operator.conversation.list``), name for name.

Killing mutations (each recorded red in the row's close):

* a verb outside the sets states ``computer=COMPUTER_REACH_LOOK``, and the exact-set pin reds;
* ``call_authorization._GRANT_REACHES`` lets Look reach ``chat``, and the exact-set pin reds;
* ``dispatch.handle_request`` passes no ``computer_reach``, and the dispatcher test sees Look refused;
* ``registry.method`` drops its reach check, and the registration test admits a bad word.
"""

from __future__ import annotations

import pytest

from agent_runtime import call_authorization as ca
from agent_runtime import serve_rpc
from agent_runtime.serve_rpc import registry

#: Look, exactly: the phone's agents, their chats and history, the office stream, files and pictures.
LOOK = frozenset({
    "runtime.health",
    "runtime.office.get",
    "runtime.office.subscribe",
    "runtime.office.unsubscribe",
    "runtime.events.after",
    "runtime.agent.directory",
    "runtime.persona.instance.detail",
    "runtime.persona.chat.history",
    "runtime.persona.chat.history.search",
    "runtime.persona.chat.content",
    "runtime.operator.conversation.list",
    "runtime.workspace.conversations",
    "runtime.character.portrait",
    "runtime.characters.thumb",
    "runtime.profiles.avatar",
    "runtime.agent.files.tree",
    "runtime.agent.files.read",
    "runtime.agent.files.grep",
    # Kept at Look by the owner's "3 yes" (RT-FU-WHETHER-A-LOOK-COMPUTER-MAY-READ-A-PHONES-GENERATED-DOCUMENTS).
    "runtime.agent.files.virtual",
    "runtime.media.index",
    "runtime.media.get",
    # One agent's prompt details, read when its panel opens: the exposure the agent-list frame's section had
    # (hermes a0982c37d578, RT-FU-AN-AGENTS-PROMPT-DETAILS-ARE-BUILT-WHEN-ITS-PANEL-OPENS-NOT-ON-EVERY-AGENT-LIST),
    # its local paths withheld below console reach (754baf98922f).
    "runtime.prompt_observability.agent",
})

#: What Run chats adds, exactly.
CHAT_ONLY = frozenset({
    "runtime.chat.message",
    "runtime.chat.steer",
    "runtime.chat.turn.resolve",
    "runtime.persona.instance.open_chat",
    "runtime.agent.conversation.create",
    "runtime.client.capabilities",
    "runtime.operator.conversation.read",
    "runtime.agent.idle_instances",
})

#: Named by the row: never reached by a grant below the account level.
NEVER = ("runtime.agent.files.virtual.write", "runtime.provider.key.set", "runtime.provider.signin.begin",
         "runtime.gateway.devices.list", "runtime.gateway.reverse.grant", "runtime.default_model.set")


def test_the_stated_reaches_are_exactly_the_two_allowlists_as_they_stood():
    assert registry.COMPUTER_LOOK_METHOD_ALLOWLIST == LOOK
    assert registry.COMPUTER_CHAT_METHOD_ALLOWLIST == LOOK | CHAT_ONLY
    assert set(registry.computer_reach()) == LOOK | CHAT_ONLY
    for name in NEVER:
        assert registry.method_computer_reach(name) is None, name
    assert not (LOOK | CHAT_ONLY) & ca.LOCAL_CONSOLE_METHODS


def test_the_manifest_publishes_the_stated_reach():
    published = serve_rpc.manifest()["computer_reach"]
    assert published == {**{name: "look" for name in LOOK}, **{name: "chat" for name in CHAT_ONLY}}


def _computer(grant):
    return ca.RpcCaller(kind=ca.CALLER_COMPUTER, transport="gateway", connection_key="lane-1",
                        computer_id="cmp-1", computer_grant=grant)


def _ask(name, grant, params=None):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "r", "method": name, "params": params or {}},
                                    serve_rpc.RpcContext(caller=_computer(grant)))


def _denied(frame):
    return frame.get("error", {}).get("data", {}).get("reason") == ca.REASON_SCOPE_DENIED


def test_the_dispatcher_hands_the_stated_reach_to_the_gate():
    assert "result" in _ask("runtime.health", "look")
    assert not _denied(_ask("runtime.chat.message", "chat"))
    refused = _ask("runtime.chat.message", "look")
    assert _denied(refused) and "Run chats" in refused["error"]["message"]
    for grant in ("look", "chat"):
        assert _denied(_ask("runtime.characters.list", grant)), grant
        assert _denied(_ask("runtime.agent.files.virtual.write", grant)), grant


def test_a_verb_cannot_state_an_unknown_reach_or_one_on_a_console_only_verb():
    with pytest.raises(ValueError, match="unknown computer reach"):
        registry.method("runtime.test.reach", "read", computer="account")
    console_only = sorted(ca.LOCAL_CONSOLE_METHODS)[0]
    with pytest.raises(ValueError, match="cannot state a computer reach"):
        registry.method(console_only, "console", computer="look")
