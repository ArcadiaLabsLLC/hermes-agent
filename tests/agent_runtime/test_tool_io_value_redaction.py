"""The operator tool-IO lane scrubs secret VALUES, never words or field names.

Reproduces the 2026-10-02 18:52Z QA turn (archive events.81417412 line 18100):
``open_app_tab`` refused with an ``auth_required`` envelope inside an ``error``
string, one line of JSON whose prose said "no access token". The console showed
``[redacted line — contained a secret]`` and nothing else; the verdict, the
message and the next step were all lost, and no secret was in the result.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.profile_runner.tool_payloads import _tool_finished_payload, _tool_started_payload
from agent_runtime.progress import _safe_progress_payload
from agent_runtime.redaction import REDACTED_VALUE, is_secret_field_name, scrub_secret_value_tree

_TOOL = "mcp__launcher_qa__mcp_launcher_qa_open_app_tab"
_INVOCATION = {"dismiss_onboarding": True, "reap_stale": False, "screenshot": False, "tab": "news"}

# Built, never spelled: fake credential VALUES in each shape the lane must catch.
_FAKE_JWT = "eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20
_FAKE_SK = "sk-" + "Z9" * 12
_FAKE_BEARER = "Q" * 28


def _auth_required_envelope(**extra) -> dict:
    """The evidence turn's envelope, padded past the 1600-char head bound the way
    the real one was (its ``app`` section alone ran over a kilobyte)."""

    envelope = {
        "schema": "stagec_mcp_open_app_tab.safe.v1",
        "generated_at": "2026-10-02T18:52:40.020360Z",
        "app": {
            "transport": "direct_control",
            "launched_this_call": True,
            "profile": "stagec-smoke",
            "control_registry": {"state": "populated", "scopes": ["account.overlay", "shell.nav"] * 40},
        },
        "ok": False,
        "failure_class": "auth_required",
        "message_safe": (
            "Launcher is not authenticated (status=unauthenticated). Pass browser_login:true to run "
            "the staging login flow in-process, or call mcp_launcher_qa_dev_login first (QA builds; "
            "no access token) and retry."
        ),
        "warnings": [],
        "suggested_next_action": (
            "Call mcp_launcher_qa_dev_login; or retry with "
            '{"browser_login": true, "credential_profile": "stagec-smoke"}'
        ),
    }
    envelope.update(extra)
    return envelope


def _console_tool_result(raw_result: str) -> str:
    """What the operator console persists: producer payload, then the sink."""

    payload = _tool_finished_payload(
        "run.tool.finished", _TOOL, duration=220.77, is_error=True,
        result=raw_result, invocation=_INVOCATION,
    )
    return _safe_progress_payload("run.tool.finished", payload)["tool_result"]


def test_an_auth_refusal_reaches_the_console_with_its_verdict_and_next_step():
    raw = json.dumps({"error": json.dumps(_auth_required_envelope())})
    assert len(raw) > 1600  # the evidence result was cut by the head bound too

    shown = _console_tool_result(raw)

    assert "[redacted line" not in shown
    head = shown.split("\n")
    assert head[0] == "ok: false"
    assert head[1] == 'failure_class: "auth_required"'
    assert head[2].startswith("message_safe: ") and "no access token" in head[2]
    assert head[3].startswith("suggested_next_action: ") and "credential_profile" in head[3]


def test_a_secret_value_in_the_same_result_is_still_scrubbed():
    """Positive control: same envelope, real-shaped secrets added. Every VALUE
    goes; every field name and the verdict stay."""

    # Ahead of the long ``app`` section, so the head bound is not what hides them.
    envelope = {
        "access_token": _FAKE_JWT,
        "session": {"client_secret": "local-dev-shared-value", "user": "tony"},
        **_auth_required_envelope(
            message_safe=f"login failed: Authorization: Bearer {_FAKE_BEARER} rejected; key {_FAKE_SK}",
        ),
    }
    raw = json.dumps({"error": json.dumps(envelope)})

    shown = _console_tool_result(raw)

    for secret in (_FAKE_JWT, _FAKE_SK, _FAKE_BEARER, "local-dev-shared-value"):
        assert secret not in shown
    assert f'access_token: "{REDACTED_VALUE}"' in shown
    assert 'failure_class: "auth_required"' in shown
    assert '"user": "tony"' in shown
    assert "login failed" in shown


def test_tool_input_keeps_field_names_and_drops_secret_values():
    # A passphrase with spaces: only the field rule removes all of it -- the prose
    # assignment rule stops at the first space.
    invocation = {"credential_profile": "stagec-smoke", "password": "correct horse battery staple", "tab": "news"}
    payload = _tool_started_payload("run.tool.started", _TOOL, invocation=invocation)

    shown = _safe_progress_payload("run.tool.started", payload)["tool_input"]

    assert 'credential_profile: "stagec-smoke"' in shown
    assert "horse battery staple" not in shown
    assert f'password: "{REDACTED_VALUE}"' in shown


@pytest.mark.parametrize(
    ("key", "secret"),
    [
        ("access_token", True), ("accessToken", True), ("client_secret", True), ("x-api-key", True),
        ("password", True), ("Set-Cookie", True), ("credentials", True), ("pass\nword", True),
        ("credential_profile", False), ("token_count", False), ("max_tokens", False),
        ("secret_ref", False), ("failure_class", False),
    ],
)
def test_secret_field_names_are_read_by_their_tail(key, secret):
    assert is_secret_field_name(key) is secret


def test_a_boolean_under_a_secret_name_is_a_fact_not_a_secret():
    assert scrub_secret_value_tree({"token_present": True, "has_token": False, "token": None}) == {
        "token_present": True, "has_token": False, "token": None,
    }
