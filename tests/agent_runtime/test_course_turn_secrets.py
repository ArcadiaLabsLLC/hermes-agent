"""RT-COURSE-TURN-SECRETS — the course credential reaches a turn without riding argv.

Plan ``docs/agent-runtime-harness/archive/course-turn-credential-2026-10-25.md`` §2.1-2.3.

Killing mutations (recorded in the landing commit): fold the credential into argv
(``argv += ["--course-credential", ...]``) -> the receipt-bytes test reds; skip the
``turn_secrets.drop`` in the serve's turn wrapper -> the after-turn ``get`` test reds.
"""

from __future__ import annotations

import pytest

from agent_runtime import paths, turn_secrets
from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD, normalize_chat_message, perform_chat_turn
from agent_runtime.realm_membership import RealmSyncCredential
from hermes_cli.harness_parts.serve.lanes import _run_with_turn_secrets

SECRET = "Basic c2VjcmV0LWNvdXJzZS1naXQtYXV0aA=="


def _credential(**overrides) -> dict:
    return {"schema_version": 1, "realm_id": "course:crs_demo", "api_base": "https://api.test.invalid/api",
            "api_token": "etk_course_bearer", "git_url": "https://github.com/o/r.git",
            "git_authorization": SECRET, "expires_at": "2999-01-01T00:00:00Z", **overrides}


def _params(**extra) -> dict:
    return {"turn_request_id": "turn-course-1", "persona_id": "dev", "message": "fix the quiz", **extra}


def test_the_credential_is_a_turn_secret_and_never_argv():
    plain = normalize_chat_message(_params())
    with_credential = normalize_chat_message(_params(course_credential=_credential()))
    assert with_credential.argv == plain.argv
    assert isinstance(with_credential.secrets["course_credential"], RealmSyncCredential)
    assert plain.secrets == {}


@pytest.mark.parametrize("raw, reason", [
    ({"realm_id": "course:x"}, "course_credential_invalid"),
    (_credential(expires_at="2000-01-01T00:00:00Z"), "course_credential_expired"),
])
def test_a_bad_credential_refuses_at_the_door(raw, reason):
    outcome = perform_chat_turn(_params(course_credential=raw), verb=CHAT_MESSAGE_METHOD,
                                spawn=lambda *_args: pytest.fail("a refused send must not spawn"))
    assert outcome.refusal is not None and outcome.refusal.data["reason"] == reason


def test_the_receipt_never_holds_the_credential_and_a_replay_without_it_is_the_same_message():
    spawned: list[tuple] = []
    held: list = []

    def spawn(request_id, argv, turn_request_id):
        spawned.append((request_id, list(argv), turn_request_id))
        with turn_secrets.bound(turn_request_id):
            held.append(turn_secrets.get("course_credential"))

    first = perform_chat_turn(_params(course_credential=_credential()), verb=CHAT_MESSAGE_METHOD, spawn=spawn)
    assert first.refusal is None and first.result["accepted"] is True
    assert isinstance(held[0], RealmSyncCredential), "the turn reads its credential"
    assert not any(SECRET in item or "etk_course_bearer" in item for item in spawned[0][1])
    receipts = list(paths.chat_turn_reservations_dir().glob("*.json"))
    assert receipts, "the accept receipt was written"
    for receipt in receipts:
        text = receipt.read_text(encoding="utf-8")
        assert SECRET not in text and "etk_course_bearer" not in text

    replay = perform_chat_turn(_params(), verb=CHAT_MESSAGE_METHOD, spawn=spawn)
    assert replay.refusal is None and replay.result["idempotent_replay"] is True
    turn_secrets.drop("turn-course-1")


def test_the_serve_wrapper_binds_the_turn_and_drops_its_secrets_however_it_ends():
    turn_secrets.put("turn-course-2", {"course_credential": "held"})
    seen: list = []

    def run(_request):
        seen.append(turn_secrets.get("course_credential"))
        raise RuntimeError("the turn failed")

    with pytest.raises(RuntimeError):
        _run_with_turn_secrets(run, "turn-course-2", object())
    assert seen == ["held"]
    with turn_secrets.bound("turn-course-2"):
        assert turn_secrets.get("course_credential") is None, "a finished turn leaves nothing behind"


def test_an_unbound_context_reads_nothing():
    """Positive control for ``get``: the same held secret, read with no turn bound."""

    turn_secrets.put("turn-course-3", {"course_credential": "held"})
    assert turn_secrets.get("course_credential") is None
    with turn_secrets.bound("turn-course-3"):
        assert turn_secrets.get("course_credential") == "held"
    turn_secrets.drop("turn-course-3")
