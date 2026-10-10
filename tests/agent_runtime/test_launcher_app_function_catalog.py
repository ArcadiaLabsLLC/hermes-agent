"""The Launcher's app functions, per connection (Stage 7 harness half, lane w10-s7h).

What the first slice (``test_launcher_app_functions``) did not pin: the list is
asked ONCE per admitted connection and forgotten on reconnect; every request
the runtime sends states its origin; a closed connection fails its open
request at once and never resends it; the Launcher's typed refusals and the
confirmation outcome reach the model read; ``read_only`` blocks the confirm
entries through the one permission chokepoint; the Studio set is offered only
because the Launcher listed it; the operator lane stamps persona instance and
profile on the invocation.

Contract: ``EterniaLauncher/docs/embedded_hermes/planned/IMPLEMENTATION_2026-09-28.md``,
"Stage 7 launcher half as landed"; refusal words from
``EterniaLauncher/lib/features/mission_control/data/app_functions/app_function_dispatcher.dart``.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from agent_runtime import launcher_app_function_answers as answers
from agent_runtime import launcher_app_functions as laf
from agent_runtime import launcher_client_requests as lcr
from tests.agent_runtime.test_launcher_app_functions import _TOOLS, _Launcher, _declare

_CONFIRM_TOOL = {
    "name": "launcher_settings_set",
    "method": "launcher.settings.set",
    "description": "Change a setting.",
    "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "value": {}}},
    "requires_confirmation": True,
    "reach": "local",
}
_STUDIO_TOOL = {
    "name": "launcher_studio_project_list",
    "method": "launcher.studio.project.list",
    "description": "List Studio projects.",
    "parameters": {"type": "object", "properties": {}},
}
#: The Launcher's eight refusals and the JSON-RPC code each carries.
_LAUNCHER_REFUSALS = {
    "unknown_function": -32601,
    "invalid_arguments": -32602,
    "refused_by_policy": -32001,
    "not_reachable_from_caller": -32002,
    "opt_in_off": -32003,
    "confirmation_declined": -32004,
    "unavailable": -32005,
    "failed": -32006,
}


class _TypedLauncher(_Launcher):
    """A Launcher whose refusals carry the dispatcher's typed word and code."""

    def __init__(self, tools=None, *, refusals=None, hold=None):
        super().__init__(tools)
        self.refusals = refusals or {}
        #: Methods whose answer is withheld until ``release`` is set.
        self.hold = hold or set()
        self.release = threading.Event()

    def _answer(self, frame):
        method = frame["method"]
        if method in self.hold:
            self.release.wait(5)
            if not self.release.is_set():
                return None
        if method in self.refusals:
            name, code = self.refusals[method]
            return {"jsonrpc": "2.0", "id": frame["id"],
                    "error": {"code": code, "message": f"the Launcher said {name}", "data": {"refusal": name}}}
        return super()._answer(frame)

    def emit(self, frame):
        self.sent.append(frame)
        if "method" not in frame:
            return

        def answer():
            reply = self._answer(frame)
            if reply is not None:
                lcr.resolve_response(reply, self)

        threading.Thread(target=answer, daemon=True).start()


@pytest.fixture(autouse=True)
def _clean():
    laf._reset_for_tests()
    yield
    laf._reset_for_tests()


def _call(name, args, link):
    from tools.registry import registry

    token = laf.bind_launcher_link(link)
    try:
        return json.loads(registry.dispatch(name, args))
    finally:
        laf.reset_launcher_link(token)


def _lists(launcher):
    return [frame for frame in launcher.sent if frame.get("method") == laf.LIST_METHOD]


# ── the catalog: once per connection, forgotten on reconnect ──────────────────


def test_the_list_is_asked_once_per_connection_and_again_once_it_closed():
    launcher = _Launcher()
    link = laf.LauncherLink(launcher, laf.ORIGIN_LOCAL)

    first = laf.refresh_app_function_tools(link)
    second = laf.refresh_app_function_tools(link)

    assert first == second == ["launcher_library_list", "launcher_navigation_open"]
    assert len(_lists(launcher)) == 1
    laf.forget_launcher_connection(launcher)
    assert laf.refresh_app_function_tools(link) == first  # positive control: forgotten, asked again
    assert len(_lists(launcher)) == 2


def test_a_second_connection_never_flips_the_registry():
    """D1.03: the registry holds the UNION of every attached Launcher's catalog.

    Before, a second connection with a shorter list deregistered the first one's tools and
    the first one's next turn re-registered them: every flip a ``registry.generation`` move
    and a chat-lane bundle rebuild. Now the first connection's tool stays registered while
    any catalog holds it, and alternating turns move nothing.
    """

    from tools.registry import registry

    first, second = _Launcher(), _Launcher(_TOOLS[:1])
    laf.refresh_app_function_tools(laf.LauncherLink(first, laf.ORIGIN_LOCAL))
    laf.refresh_app_function_tools(laf.LauncherLink(second, laf.ORIGIN_LOCAL))
    assert registry.get_entry("launcher_navigation_open") is not None

    generation = registry.generation
    for _ in range(3):
        laf.refresh_app_function_tools(laf.LauncherLink(first, laf.ORIGIN_LOCAL))
        laf.refresh_app_function_tools(laf.LauncherLink(second, laf.ORIGIN_LOCAL))

    assert registry.generation == generation
    assert len(_lists(first)) == len(_lists(second)) == 1  # from the catalog, not the wire


def _definition_names(link):
    from model_tools import get_tool_definitions

    token = laf.bind_launcher_link(link)
    try:
        return {d["function"]["name"] for d in get_tool_definitions(
            enabled_toolsets=[laf.APP_FUNCTIONS_TOOLSET], quiet_mode=True,
            skip_tool_search_assembly=True)}
    finally:
        laf.reset_launcher_link(token)


_B_ONLY_TOOL = {
    "name": "launcher_b_only_probe",
    "method": "launcher.b_only.probe",
    "description": "Only connection B declares this.",
    "parameters": {"type": "object", "properties": {}},
}


def test_each_turn_sees_only_its_own_launchers_tools():
    a, b = _Launcher(), _Launcher([_TOOLS[0], _B_ONLY_TOOL])
    link_a, link_b = laf.LauncherLink(a, laf.ORIGIN_LOCAL), laf.LauncherLink(b, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link_a)
    laf.refresh_app_function_tools(link_b)

    assert _definition_names(link_a) == {"launcher_library_list", "launcher_navigation_open"}
    assert _definition_names(link_b) == {"launcher_library_list", "launcher_b_only_probe"}
    assert _definition_names(None) == set()  # no Launcher on the turn: nothing offered


def test_forgetting_a_connection_removes_only_the_names_no_other_catalog_holds():
    from tools.registry import registry

    a, b = _Launcher(), _Launcher([_TOOLS[0], _B_ONLY_TOOL])
    laf.refresh_app_function_tools(laf.LauncherLink(b, laf.ORIGIN_LOCAL))
    laf.refresh_app_function_tools(laf.LauncherLink(a, laf.ORIGIN_LOCAL))  # A's turn last

    laf.forget_launcher_connection(a)

    assert registry.get_entry("launcher_navigation_open") is None  # A-only: gone
    assert registry.get_entry("launcher_library_list") is not None  # B still declares it
    assert registry.get_entry("launcher_b_only_probe") is not None


def test_a_re_declaration_lists_afresh():
    launcher = _Launcher()
    link = laf.LauncherLink(launcher, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    _declare("stdio")
    laf.refresh_app_function_tools(link)
    assert len(_lists(launcher)) == 2


def test_forgetting_the_only_connection_empties_the_toolset():
    launcher = _Launcher()
    laf.refresh_app_function_tools(laf.LauncherLink(launcher, laf.ORIGIN_LOCAL))
    assert laf.app_function_tools_registered()
    laf.forget_launcher_connection(launcher)
    assert not laf.app_function_tools_registered()


def test_the_serve_disconnect_path_forgets_the_connections_sink():
    """The join: ``_on_connection_closed`` hands the departed connection's OWN
    sink to ``forget_launcher_connection``; another connection's catalog stays."""

    from types import SimpleNamespace

    from hermes_cli.harness_parts.serve.subscriptions import SubscriptionLanes

    class Lanes(SubscriptionLanes):
        def __init__(self, sinks):
            self.connection_sinks = dict(sinks)
            self.connection_sinks_lock = threading.Lock()
            # The serve session's in-flight table (``session.py``): the disconnect
            # path also cancels the departed owner's queued requests; none here.
            self.inflight = {}
            self.inflight_futures = {}
            self.inflight_lock = threading.Lock()
            self.released = []

        def _release_subscription(self, connection):
            self.released.append(connection.key)

        def _reclaim_abandoned_streams(self, connection):
            return 0

    going, staying = _Launcher(), _Launcher(_TOOLS[:1])
    laf.refresh_app_function_tools(laf.LauncherLink(going, laf.ORIGIN_LOCAL))
    laf.refresh_app_function_tools(laf.LauncherLink(staying, laf.ORIGIN_LOCAL))
    lanes = Lanes({"sock-1": going, "sock-2": staying})

    lanes._on_connection_closed(SimpleNamespace(key="sock-1"))

    assert lanes.released == ["sock-1"]
    laf.refresh_app_function_tools(laf.LauncherLink(going, laf.ORIGIN_LOCAL))
    laf.refresh_app_function_tools(laf.LauncherLink(staying, laf.ORIGIN_LOCAL))
    assert len(_lists(going)) == 2 and len(_lists(staying)) == 1


# ── origin on every request ────────────────────────────────────────────────────


@pytest.mark.parametrize("origin", [laf.ORIGIN_LOCAL, laf.ORIGIN_PAIRED_DEVICE])
def test_every_request_the_runtime_sends_states_the_turns_origin(origin):
    launcher = _Launcher()
    link = laf.LauncherLink(launcher, origin)
    laf.refresh_app_function_tools(link)
    _call("launcher_library_list", {}, link)
    _call("launcher_navigation_open", {"page": "shop", "_meta": {"origin": "unknown"}}, link)

    requests = [frame for frame in launcher.sent if "method" in frame]
    assert [frame["method"] for frame in requests] == [
        laf.LIST_METHOD, "launcher.library.list", "launcher.navigation.open"]
    assert all(frame["params"]["_meta"]["origin"] == origin for frame in requests)


# ── a closed connection: fail now, never resend ────────────────────────────────


def test_a_closed_connection_fails_its_open_request_now_and_never_resends_it(monkeypatch):
    monkeypatch.setattr(laf, "CALL_TIMEOUT_SECONDS", 30.0)
    launcher = _TypedLauncher(hold={"launcher.library.list"})
    replacement = _Launcher()
    link = laf.LauncherLink(launcher, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    result = {}
    worker = threading.Thread(target=lambda: result.update(_call("launcher_library_list", {}, link)))
    worker.start()
    deadline = time.monotonic() + 5
    while lcr.CLIENT_REQUESTS.open_count() == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert lcr.CLIENT_REQUESTS.open_count() == 1

    started = time.monotonic()
    laf.forget_launcher_connection(launcher)
    worker.join(5)
    launcher.release.set()

    assert not worker.is_alive() and time.monotonic() - started < 5
    assert result["refusal"] == lcr.CONNECTION_CLOSED
    assert result["retry"] == answers.RETRY_NEVER
    laf.refresh_app_function_tools(laf.LauncherLink(replacement, laf.ORIGIN_LOCAL))
    assert [frame["method"] for frame in replacement.sent] == [laf.LIST_METHOD]


# ── the Launcher's typed answers, read for the model ───────────────────────────


@pytest.mark.parametrize("name,code", sorted(_LAUNCHER_REFUSALS.items()))
def test_each_launcher_refusal_reaches_the_model_read(name, code):
    launcher = _TypedLauncher(refusals={"launcher.navigation.open": (name, code)})
    link = laf.LauncherLink(launcher, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)

    result = _call("launcher_navigation_open", {"page": "library"}, link)

    meaning = answers.LAUNCHER_REFUSALS[name]
    assert (result["refusal"], result["code"]) == (name, code)
    assert (result["retry"], result["detail"]) == (meaning.retry, meaning.detail)
    assert "error" in result and "data" not in result


def test_reach_closed_on_a_paired_device_turn_is_final_for_the_model():
    launcher = _TypedLauncher(refusals={"launcher.navigation.open": ("not_reachable_from_caller", -32002)})
    link = laf.LauncherLink(launcher, laf.ORIGIN_PAIRED_DEVICE)
    laf.refresh_app_function_tools(link)

    result = _call("launcher_navigation_open", {"page": "library"}, link)

    assert result["retry"] == answers.RETRY_NEVER
    assert launcher.sent[-1]["params"]["_meta"]["origin"] == laf.ORIGIN_PAIRED_DEVICE
    assert result["refusal"] == "not_reachable_from_caller"


def test_a_confirm_entry_reports_the_persons_answer():
    from tools.registry import registry

    approved = _TypedLauncher([_CONFIRM_TOOL])
    link = laf.LauncherLink(approved, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    assert "approval" in registry.get_entry("launcher_settings_set").schema["description"]
    assert _call("launcher_settings_set", {"key": "theme", "value": "dark"}, link)["confirmed"] is True

    laf._reset_for_tests()
    declined = _TypedLauncher([_CONFIRM_TOOL], refusals={"launcher.settings.set": ("confirmation_declined", -32004)})
    link = laf.LauncherLink(declined, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    result = _call("launcher_settings_set", {"key": "theme", "value": "dark"}, link)

    assert result["confirmed"] is False
    assert (result["refusal"], result["retry"]) == ("confirmation_declined", answers.RETRY_NEVER)

    laf._reset_for_tests()  # positive control: an entry needing no approval carries no verdict
    link = laf.LauncherLink(_TypedLauncher([_TOOLS[1]]), laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    assert "confirmed" not in _call("launcher_navigation_open", {"page": "shop"}, link)


def test_an_unlisted_launcher_word_is_still_handed_to_the_model():
    launcher = _TypedLauncher(refusals={"launcher.navigation.open": ("rate_limited", -32099)})
    link = laf.LauncherLink(launcher, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    result = _call("launcher_navigation_open", {}, link)
    assert result["refusal"] == "rate_limited" and result["retry"] == answers.RETRY_LATER


def test_no_launcher_on_the_turn_is_a_typed_refusal():
    from tools.registry import registry

    laf.refresh_app_function_tools(laf.LauncherLink(_Launcher(), laf.ORIGIN_LOCAL))
    result = json.loads(registry.dispatch("launcher_library_list", {}))
    assert (result["refusal"], result["retry"]) == ("no_launcher", answers.RETRY_NEVER)


# ── the permission chokepoint ──────────────────────────────────────────────────


def test_read_only_blocks_the_confirm_entries_through_the_one_chokepoint():
    from agent_runtime.chat_lane_bundle import _blocked_tool_names_for_chat
    from agent_runtime.permission_modes import PERMISSION_MODE_READ_ONLY, PERMISSION_MODE_UNBOUNDED
    from agent_runtime.tool_permissions import (
        READ_ONLY_BLOCKS,
        ChatToolPermissionStore,
        extra_blocked_tools_for_permission_mode,
        permission_options_for_chat,
    )
    from tests.agent_runtime.test_unbounded_default_posture import _persona

    laf.refresh_app_function_tools(laf.LauncherLink(_Launcher([*_TOOLS, _CONFIRM_TOOL]), laf.ORIGIN_LOCAL))

    assert laf.mutating_app_function_tools() == {"launcher_settings_set"}
    assert set(extra_blocked_tools_for_permission_mode(PERMISSION_MODE_READ_ONLY)) == READ_ONLY_BLOCKS | {"launcher_settings_set"}
    assert extra_blocked_tools_for_permission_mode(PERMISSION_MODE_UNBOUNDED) == []

    persona = _persona()
    ChatToolPermissionStore().set(persona_id=persona.id, session_id="chat-ro", mode=PERMISSION_MODE_READ_ONLY,
                                  reason="review only", source="operator")
    options = permission_options_for_chat(persona, session_id="chat-ro")
    assert "launcher_settings_set" in options.blocked_tool_names
    assert "launcher_library_list" not in options.blocked_tool_names
    assert "launcher_settings_set" in _blocked_tool_names_for_chat(persona, session_id="chat-ro")


def test_read_only_blocks_and_labels_by_the_launchers_read_only_mark():
    """The Launcher marks each entry ``read_only`` (lane mc-a): a mutating entry that needs
    no approval is still blocked in ``read_only`` mode and labelled mutating, and a confirm
    entry the Launcher marks read-only is not. Positive control: an entry with no mark
    falls back to ``requires_confirmation``."""

    from agent_runtime.permission_modes import PERMISSION_MODE_READ_ONLY
    from agent_runtime.tool_permissions import extra_blocked_tools_for_permission_mode
    from agent_runtime.tool_visibility import _mutating_tools

    silent_write = {**_TOOLS[0], "name": "launcher_queue_clear", "method": "launcher.queue.clear",
                    "requires_confirmation": False, "read_only": False}
    confirmed_read = {**_CONFIRM_TOOL, "name": "launcher_vault_peek", "method": "launcher.vault.peek",
                      "read_only": True}
    unmarked_confirm = {k: v for k, v in _CONFIRM_TOOL.items() if k != "read_only"}
    assert "launcher_queue_clear" not in _mutating_tools()  # read BEFORE the catalog lands: no stale cache
    laf.refresh_app_function_tools(laf.LauncherLink(
        _Launcher([*_TOOLS, silent_write, confirmed_read, unmarked_confirm]), laf.ORIGIN_LOCAL))

    blocked = set(extra_blocked_tools_for_permission_mode(PERMISSION_MODE_READ_ONLY))
    assert "launcher_queue_clear" in blocked
    assert "launcher_vault_peek" not in blocked
    assert "launcher_settings_set" in blocked  # no mark: the confirm fallback
    assert {"launcher_queue_clear", "launcher_settings_set"} <= _mutating_tools()
    assert "launcher_vault_peek" not in _mutating_tools()


# ── the Studio set stays behind the Launcher's gate ────────────────────────────


def test_the_studio_set_is_offered_only_because_the_launcher_listed_it():
    from tools.registry import registry

    closed = _Launcher(_TOOLS)  # the gate is closed: the Launcher does not list Studio
    link = laf.LauncherLink(closed, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    assert registry.get_entry("launcher_studio_project_list") is None
    assert "Unknown tool" in json.loads(_call_raw("launcher_studio_project_list", {}, link))["error"]
    assert not any(frame.get("method", "").startswith("launcher.studio.") for frame in closed.sent)

    opened = _Launcher([*_TOOLS, _STUDIO_TOOL])  # positive control: the gate is open, so it is listed
    link = laf.LauncherLink(opened, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    assert registry.get_entry("launcher_studio_project_list").toolset == laf.APP_FUNCTIONS_TOOLSET
    _call("launcher_studio_project_list", {}, link)
    assert opened.sent[-1]["method"] == "launcher.studio.project.list"


def _call_raw(name, args, link):
    from tools.registry import registry

    token = laf.bind_launcher_link(link)
    try:
        return registry.dispatch(name, args)
    finally:
        laf.reset_launcher_link(token)


# ── the operator lane's invocation ─────────────────────────────────────────────


def test_the_invocation_carries_persona_instance_and_profile_when_the_lane_knows_them():
    from agent_runtime.launcher_invocation import launcher_invocation

    launcher = _Launcher()
    link = laf.LauncherLink(launcher, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    with launcher_invocation("operator", "chat-1", "turn-1", persona_instance_id="pi-7", profile="base"):
        _call("launcher_library_list", {}, link)
    stamped = launcher.sent[-1]["params"]["_meta"]
    assert stamped["origin"] == laf.ORIGIN_LOCAL
    assert stamped["invocation"] == {"channel": "operator", "session_id": "chat-1", "turn_id": "turn-1",
                                     "persona_instance_id": "pi-7", "profile": "base"}
    with launcher_invocation("operator", "chat-1", "turn-2"):
        _call("launcher_library_list", {}, link)
    assert set(launcher.sent[-1]["params"]["_meta"]["invocation"]) == {"channel", "session_id", "turn_id"}


def test_invalid_arguments_is_not_read_to_the_model_as_a_schema_failure():
    """The Launcher answers ``invalid_arguments`` for any argument it cannot use —
    on 2026-10-09 a JSON syntax error inside ``document_json`` — so a fixed
    'did not validate against the schema' sent the model to repair the wrong
    thing. The message carries the specifics; the reading must not contradict it."""

    meaning = answers.LAUNCHER_REFUSALS["invalid_arguments"]
    assert meaning.retry == answers.RETRY_AFTER_CHANGE
    assert "schema" not in meaning.detail
    assert "message" in meaning.detail
