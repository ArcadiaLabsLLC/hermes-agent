"""``runtime.provider.*`` — each method over fakes of the upstream code it wraps (no network).

Every test names its killing mutation; the reds are recorded in the commit
that added the family.
"""

from __future__ import annotations

import json
import queue
import time
from datetime import datetime, timezone

import pytest

from agent_runtime import provider_signin, provider_signin_child
from agent_runtime.serve_rpc import DEFERRED, RpcContext
from agent_runtime.serve_rpc import provider as family
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_HANDLER_FAILED, ERR_INVALID_PARAMS, ERR_NOT_FOUND

SECRET = "SENTINEL-SECRET-TOKEN"


def _result(frame: dict) -> dict:
    assert "error" not in frame, frame
    assert SECRET not in json.dumps(frame)
    return frame["result"]


def _error(frame: dict) -> dict:
    assert "result" not in frame, frame
    assert SECRET not in json.dumps(frame)
    return frame["error"]


# ── fake sign-in child ───────────────────────────────────────────────────────


class FakeChild:
    def __init__(self, provider: str, flow: str, profile: str | None) -> None:
        self.provider, self.flow, self.profile = provider, flow, profile
        self.out: queue.Queue = queue.Queue()
        self.written: list[str] = []
        self.terminated = False

    def emit(self, **event) -> None:
        self.out.put(json.dumps(event))

    def exit(self) -> None:
        self.out.put(None)

    def lines(self):
        while (line := self.out.get()) is not None:
            yield line

    def write_line(self, text: str) -> None:
        self.written.append(text)

    def terminate(self) -> None:
        self.terminated = True
        self.exit()


@pytest.fixture
def signins(monkeypatch):
    children: list[FakeChild] = []
    clock = {"now": 1000.0}

    def spawn(provider, flow, profile):
        children.append(FakeChild(provider, flow, profile))
        return children[-1]

    registry = provider_signin.ProviderSignIns(spawn=spawn, clock=lambda: clock["now"])
    monkeypatch.setattr(provider_signin, "_REGISTRY", registry)
    yield children, clock
    for child in children:
        child.exit()


def _poll(login_id: str) -> dict:
    return _result(family._runtime_provider_signin_poll(1, {"login_id": login_id}))


def _await_state(login_id: str, state: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        view = _poll(login_id)
        if view["state"] == state:
            return view
        time.sleep(0.01)
    pytest.fail(f"{login_id} never reached {state}: {_poll(login_id)}")


def _begin(**params) -> dict:
    return family._runtime_provider_signin_begin(1, params)


def test_device_code_sign_in_surfaces_the_verification_then_succeeds(signins):
    """Killing mutation: ``_apply``'s ``code`` arm not setting ``verification_uri`` -> red."""
    children, _ = signins
    view = _result(_begin(provider="nous"))
    assert (view["state"], view["flow"], view["contract"]) == ("starting", "device_code", 1)
    child = children[0]
    child.emit(event="code", verification_uri="https://portal.example/device", user_code="ABCD-1234", home="h")
    view = _await_state(view["login_id"], "awaiting_user")
    assert (view["verification_uri"], view["user_code"], view["needs_code"]) == (
        "https://portal.example/device", "ABCD-1234", False)
    child.emit(event="done", ok=True, access_token=SECRET)
    view = _await_state(view["login_id"], "succeeded")
    assert "error_code" not in view


def test_paste_code_sign_in_needs_complete_and_writes_the_code_to_the_child(signins):
    """Killing mutation: ``complete`` skipping ``child.write_line(code)`` -> red."""
    children, _ = signins
    view = _result(_begin(provider="anthropic"))
    assert view["flow"] == "paste_code"
    children[0].emit(event="code", verification_uri="https://claude.ai/oauth/authorize?x=1", user_code="")
    view = _await_state(view["login_id"], "awaiting_code")
    assert view["needs_code"] is True
    done = _result(family._runtime_provider_signin_complete(1, {"login_id": view["login_id"], "code": "abc#st"}))
    assert done["state"] == "completing" and "abc#st" not in json.dumps(done)
    assert children[0].written == ["abc#st"]
    children[0].emit(event="done", ok=True)
    _await_state(view["login_id"], "succeeded")


def test_complete_is_refused_outside_awaiting_code(signins):
    """Killing mutation: drop the ``state != "awaiting_code"`` guard -> the code reaches a device flow, red."""
    children, _ = signins
    view = _result(_begin(provider="nous"))
    error = _error(family._runtime_provider_signin_complete(1, {"login_id": view["login_id"], "code": "x#y"}))
    assert (error["code"], error["data"]["reason"]) == (ERR_CONFLICT, "login_not_awaiting_code")
    assert children[0].written == []


@pytest.mark.parametrize("code", [None, "", "a\nb", "x" * (family.MAX_CODE_CHARS + 1)])
def test_complete_refuses_a_malformed_code(signins, code):
    """Killing mutation: remove the newline check -> a second stdin line reaches the child, red."""
    view = _result(_begin(provider="anthropic"))
    error = _error(family._runtime_provider_signin_complete(1, {"login_id": view["login_id"], "code": code}))
    assert (error["code"], error["data"]["reason"]) == (ERR_INVALID_PARAMS, "code_invalid")


def test_cancel_kills_the_child_and_is_terminal(signins):
    """Killing mutation: ``cancel`` not calling ``child.terminate()`` -> red."""
    children, _ = signins
    view = _result(_begin(provider="xai-oauth"))
    view = _result(family._runtime_provider_signin_cancel(1, {"login_id": view["login_id"]}))
    assert (view["state"], view["error_code"]) == ("cancelled", "cancelled")
    assert children[0].terminated
    children[0].emit(event="done", ok=True)
    assert _poll(view["login_id"])["state"] == "cancelled"


def test_child_error_codes_are_a_closed_set_and_a_silent_exit_fails(signins):
    """Killing mutation: pass ``event["code"]`` through unfiltered -> the foreign code surfaces, red."""
    children, _ = signins
    first = _result(_begin(provider="nous"))
    children[0].emit(event="error", ok=False, code=SECRET)
    assert _await_state(first["login_id"], "failed")["error_code"] == "login_failed"
    second = _result(_begin(provider="nous"))
    children[1].emit(event="error", ok=False, code="denied")
    assert _await_state(second["login_id"], "failed")["error_code"] == "denied"
    third = _result(_begin(provider="nous"))
    children[2].exit()
    assert _await_state(third["login_id"], "failed")["error_code"] == "login_failed"


def test_an_unfinished_login_expires_at_the_ttl(signins):
    """Killing mutation: remove the TTL check from ``poll`` -> still starting, red."""
    children, clock = signins
    view = _result(_begin(provider="nous"))
    clock["now"] += provider_signin.LOGIN_TTL_SECONDS + 1
    view = _poll(view["login_id"])
    assert (view["state"], view["error_code"]) == ("failed", "expired")
    assert children[0].terminated


def test_begin_refusals(signins):
    """Killing mutation: drop the in-progress scan in ``begin`` -> a second child spawns, red."""
    children, _ = signins
    error = _error(_begin(provider="qwen-oauth"))
    assert (error["code"], error["data"]["reason"]) == (ERR_INVALID_PARAMS, "provider_unsupported")
    error = _error(_begin(provider="nous", flow="browser"))
    assert (error["data"]["reason"], error["data"]["flows"]) == ("flow_unsupported", ["device_code"])
    error = _error(_begin())
    assert error["data"]["reason"] == "provider_required"
    first = _result(_begin(provider="nous", profile="work"))
    error = _error(_begin(provider="nous"))
    assert (error["code"], error["data"]) == (ERR_CONFLICT, {"reason": "login_in_progress", "login_id": first["login_id"]})
    assert [(c.provider, c.profile) for c in children] == [("nous", "work")]


def test_an_unknown_login_id_is_not_found(signins):
    """Killing mutation: the miss raised with family ``conflict`` -> 4090 not 4001, red."""
    error = _error(family._runtime_provider_signin_poll(1, {"login_id": "login_nope"}))
    assert (error["code"], error["data"]["reason"]) == (ERR_NOT_FOUND, "login_not_found")
    error = _error(family._runtime_provider_signin_cancel(1, {}))
    assert error["data"]["reason"] == "login_id_required"


# ── list / usage ─────────────────────────────────────────────────────────────


def test_list_is_the_provider_visibility_envelope(monkeypatch):
    """Killing mutation: ``provider_list`` returning ``{}`` -> the catalog row is gone, red."""
    from hermes_cli.harness_parts import provider_visibility

    envelope = {"schema": "hermes.provider_visibility/v2", "providers": [],
                "catalog": [{"id": "anthropic", "browser_login": True, "browser_login_methods": ["paste_code"]}]}
    monkeypatch.setattr(provider_visibility, "build_provider_visibility", lambda: envelope)
    result = _result(family._runtime_provider_list(1, {}))
    assert result == {"contract": 1, **envelope}


def test_list_runs_real_catalog_offline():
    """Positive control on the real producer. Killing mutation: drop the ``catalog`` block
    from ``build_provider_visibility`` -> KeyError, red."""
    result = _result(family._runtime_provider_list(1, {}))
    assert {row["id"] for row in result["catalog"]} >= {"anthropic", "openai-codex", "nous"}


def test_usage_projects_the_snapshot_and_drops_the_raw_body(monkeypatch):
    """Killing mutation: add ``"raw": snapshot.raw`` to ``_usage_view`` -> SECRET on the wire, red."""
    from agent import account_usage

    snapshot = account_usage.AccountUsageSnapshot(
        provider="anthropic", source="oauth_usage_api", fetched_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
        windows=(account_usage.AccountUsageWindow(label="Current session", used_percent=42.0,
                                                  reset_at=datetime(2026, 9, 28, 5, tzinfo=timezone.utc)),),
        details=("Extra usage: 1.00 / 5.00 USD",), raw={"token": SECRET})
    seen = []
    monkeypatch.setattr(account_usage, "fetch_account_usage", lambda provider, **_: seen.append(provider) or snapshot)
    result = _result(family._runtime_provider_usage(1, {"provider": "Anthropic"}))
    assert seen == ["anthropic"]
    assert result["available"] is True
    assert result["windows"] == [{"label": "Current session", "used_percent": 42.0,
                                  "reset_at": "2026-09-28T05:00:00+00:00", "detail": None}]
    assert result["details"] == ["Extra usage: 1.00 / 5.00 USD"]


def test_usage_without_a_source_is_unavailable_and_nous_fails_open_by_class(monkeypatch):
    """Killing mutation: the nous arm catching ``ValueError`` only -> TimeoutError escapes to handler_failed, red."""
    from agent import account_usage
    from hermes_cli import nous_account

    monkeypatch.setattr(account_usage, "fetch_account_usage", lambda provider, **_: None)
    assert _result(family._runtime_provider_usage(1, {"provider": "qwen-oauth"}))["available"] is False

    def boom(**_):
        raise TimeoutError(SECRET)

    monkeypatch.setattr(nous_account, "get_nous_portal_account_info", boom)
    result = _result(family._runtime_provider_usage(1, {"provider": "nous"}))
    assert (result["available"], result["unavailable_reason"]) == (False, "TimeoutError")


def test_network_methods_defer_to_the_worker_lane(monkeypatch):
    """Killing mutation: ``_off_reader`` ignoring ``spawn_reply`` -> answered inline, red."""
    from agent import account_usage

    monkeypatch.setattr(account_usage, "fetch_account_usage", lambda provider, **_: None)
    spawned = []
    context = RpcContext(spawn_reply=lambda build: spawned.append(build) or True)
    assert family._runtime_provider_usage(7, {"provider": "openrouter"}, context) is DEFERRED
    assert spawned[0]()["result"]["provider"] == "openrouter"


# ── refresh / sign-out ───────────────────────────────────────────────────────


def test_refresh_wraps_auth_refresh_and_reports_its_refusal(monkeypatch):
    """Killing mutation: swallow ``SystemExit`` as success -> refreshed:true on a refusal, red."""
    from hermes_cli import auth_commands

    calls = []
    monkeypatch.setattr(auth_commands, "auth_refresh_command", lambda args: calls.append(vars(args)))
    result = _result(family._runtime_provider_refresh(1, {"provider": "openai-codex", "credential": "2"}))
    assert (result["refreshed"], calls) == (True, [{"provider": "openai-codex", "target": "2"}])

    def refuse(args):
        raise SystemExit("openai-codex has 2 credentials; pass an index")

    monkeypatch.setattr(auth_commands, "auth_refresh_command", refuse)
    error = _error(family._runtime_provider_refresh(1, {"provider": "openai-codex"}))
    assert (error["code"], error["data"]["reason"]) == (ERR_HANDLER_FAILED, "refresh_refused")
    assert "pass an index" in error["message"]


def test_refresh_failure_names_the_class_never_the_message(monkeypatch):
    """Killing mutation: report ``str(exc)`` in ``provider_refresh`` -> SECRET on the wire, red."""
    from hermes_cli import auth_commands

    def boom(args):
        raise RuntimeError(f"refresh body {SECRET}")

    monkeypatch.setattr(auth_commands, "auth_refresh_command", boom)
    error = _error(family._runtime_provider_refresh(1, {"provider": "anthropic"}))
    assert (error["data"]["reason"], error["message"]) == ("refresh_failed", "RuntimeError")
    error = _error(family._runtime_provider_refresh(1, {"provider": "no-such-provider"}))
    assert (error["code"], error["data"]["reason"]) == (ERR_INVALID_PARAMS, "provider_unknown")


def test_signout_wraps_auth_logout_and_reports_before_and_after(monkeypatch):
    """Killing mutation: ``provider_signout`` not calling ``auth_logout_command`` -> signed_in stays true, red."""
    from hermes_cli import auth, auth_commands

    state = {"logged_in": True}
    calls = []

    def logout(args):
        calls.append(args.provider)
        state["logged_in"] = False

    monkeypatch.setattr(auth_commands, "auth_logout_command", logout)
    monkeypatch.setattr(auth, "get_auth_status", lambda provider: dict(state))
    result = _result(family._runtime_provider_signout(1, {"provider": "nous"}))
    assert (result["was_signed_in"], result["signed_in"], calls) == (True, False, ["nous"])


def test_every_provider_method_is_registered_with_its_tier():
    """Killing mutation: register ``signin.begin`` as ``read`` -> red."""
    from agent_runtime import serve_rpc

    tiers = serve_rpc.method_tiers()
    assert {name: tier for name, tier in tiers.items() if name.startswith("runtime.provider.")} == {
        "runtime.provider.list": "read", "runtime.provider.usage": "read",
        "runtime.provider.signin.begin": "console", "runtime.provider.signin.poll": "console",
        "runtime.provider.signin.complete": "console", "runtime.provider.signin.cancel": "console",
        "runtime.provider.refresh": "console", "runtime.provider.signout": "console",
    }


def test_the_default_child_is_the_machine_sign_in_verb(monkeypatch, tmp_path):
    """Killing mutation: drop ``--json`` from ``spawn_login_child``'s argv -> red."""
    captured = {}

    class Popen:
        def __init__(self, argv, **kwargs):
            captured.update(argv=argv, **kwargs)

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(provider_signin_child.subprocess, "Popen", Popen)
    provider_signin.spawn_login_child("anthropic", "paste_code", "work")
    # The fork-owned door since d97ad57e96 (plugin-owned auth commands): ``harness auth login``.
    assert captured["argv"][1:] == ["-m", "hermes_cli.main", "harness", "auth", "login", "anthropic", "--json",
                                    "--flow", "paste_code", "--profile", "work"]
    assert captured["stdin"] is provider_signin_child.subprocess.PIPE
    assert captured["stderr"] is provider_signin_child.subprocess.DEVNULL
    assert captured["env"]["HERMES_HOME"] == str(tmp_path)


def test_the_contract_publishes_a_reply_budget_for_every_provider_method():
    """``runtime-provider-methods.md`` "Reply budgets" names every registered
    ``runtime.provider.*`` method once — the Launcher derives its waits from it."""
    import re
    from pathlib import Path

    from agent_runtime.serve_rpc import registry

    doc = (Path(__file__).resolve().parents[2] / "docs" / "agent-runtime-harness"
           / "runtime-provider-methods.md").read_text(encoding="utf-8")
    section = doc.split("## Reply budgets", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(r"^\| `(runtime\.provider\.[a-z.]+)` \|.*\| (\d+) s \|$", section, re.M)
    registered = {name for name in registry.method_names() if name.startswith("runtime.provider.")}
    assert registered  # positive control: the family is registered
    assert sorted(name for name, _ in rows) == sorted(registered)
