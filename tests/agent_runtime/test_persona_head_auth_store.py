"""The theme-7 sharing seam, asserted as a POSITIVE control.

Upstream ``93889b770d`` (2026-09-16) made profiles islands: a named profile no
longer inherits the root profile's ``auth.json``, and the read-only fallback
(``hermes_cli.auth._global_auth_file_path`` / ``_load_global_auth_store``) that
implemented that inheritance was deleted by the 2026-09-17 upstream sync.

The fork still needs many persona-instance profiles under one head to reach the
credentials the operator signed in once. It does NOT get that back by inheriting.
It gets it because Mission Control explicitly BINDS the persona's active auth
store to the head's, through ``HERMES_AUTH_HOME`` — a ContextVar for in-process
readers, an env var for spawns, both written by ``persona_profile_context`` and
both read by ``hermes_constants.get_hermes_auth_home()``, which
``hermes_cli.auth._auth_file_path`` consults. That is store SELECTION, not
inheritance: there is exactly ONE active store, so a single-use refresh chain
(Codex/ChatGPT) cannot fork and no write-through bookkeeping is needed.

Why these two arms and not one: the out-of-context arm is a NEGATIVE assertion,
and a negative assertion looks identical whether the guard worked or the subject
never reached it (``docs/stages/qa-reboot/CAPTURE_IS_A_VEHICLE_2026-09-03.md``).
The in-context arm is the positive control for it — same bytes on disk, one
variable changed (the binding), and the resolution MUST happen. Together they
say the binding is what does the work, which neither says alone.

Killing mutation, applied and recorded in the commit that added this file: drop
the ``HERMES_AUTH_HOME`` pin in ``agent_runtime/profile_context.py`` (the
``auth_token = set_hermes_auth_home_override(...)`` line and the matching
``os.environ`` write). The in-context arm then resolves the persona's own empty
store and raises ``codex_auth_missing`` — the file goes red on
``test_bound_persona_resolves_the_heads_codex_provider``.
"""

import json

import pytest

from agent_runtime.profile_context import (
    PersonaProfileBinding,
    persona_profile_context,
)

_HEAD_ACCESS_TOKEN = "head-codex-access-token"
_HEAD_REFRESH_TOKEN = "head-codex-refresh-token"


def _write_codex_store(home, *, access_token, refresh_token):
    """A minimal ``auth.json`` carrying a usable ``openai-codex`` singleton."""
    payload = {
        "providers": {
            "openai-codex": {
                "tokens": {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                },
                "last_refresh": "2026-09-17T00:00:00+00:00",
            }
        }
    }
    (home / "auth.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def head_and_persona(tmp_path, monkeypatch):
    """A head home holding the only Codex credential, and a persona home with none.

    The persona directory exists and is empty of auth material on purpose: the
    claim under test is about which store is ACTIVE, and an absent directory
    would let a path bug pass for the right reason.
    """
    root = tmp_path / "hermes"
    head_home = root / "profiles" / "base"
    persona_home = root / "profiles" / "qa"
    for path in (head_home, persona_home):
        path.mkdir(parents=True)
    _write_codex_store(
        head_home, access_token=_HEAD_ACCESS_TOKEN, refresh_token=_HEAD_REFRESH_TOKEN)
    assert not (persona_home / "auth.json").exists()

    monkeypatch.setenv("HERMES_HOME", str(head_home))
    monkeypatch.delenv("HERMES_AUTH_HOME", raising=False)
    return head_home, persona_home


def _binding(persona_home):
    return PersonaProfileBinding(
        persona_id="qa",
        hermes_profile="qa",
        profile_home=persona_home,
    )


def test_bound_persona_resolves_the_heads_codex_provider(head_and_persona, monkeypatch):
    """POSITIVE CONTROL: under the binding, the head's singleton IS what resolves.

    With upstream's inheritance fallback gone, the only way this token can be
    reached from a profile that does not hold it is the active-store binding.
    """
    _head_home, persona_home = head_and_persona
    from hermes_cli.auth_codex import _read_codex_tokens
    from hermes_constants import get_hermes_home

    with persona_profile_context(_binding(persona_home)):
        # The persona really is bound to its OWN home for everything else —
        # otherwise this would prove nothing about auth specifically.
        assert get_hermes_home() == persona_home
        resolved = _read_codex_tokens()

    assert resolved["tokens"]["access_token"] == _HEAD_ACCESS_TOKEN
    assert resolved["tokens"]["refresh_token"] == _HEAD_REFRESH_TOKEN


def test_unbound_persona_does_not_reach_the_heads_codex_provider(
    head_and_persona, monkeypatch
):
    """The same profile, the same bytes on disk, WITHOUT the binding: nothing.

    This is upstream's ruling honoured — nobody inherits. It is asserted here
    only because the test above proves the subject reaches the resolver at all;
    on its own this refusal would be satisfied by any unrelated breakage.
    """
    _head_home, persona_home = head_and_persona
    from hermes_cli.auth import AuthError
    from hermes_cli.auth_codex import _read_codex_tokens

    monkeypatch.setenv("HERMES_HOME", str(persona_home))

    with pytest.raises(AuthError) as excinfo:
        _read_codex_tokens()

    assert excinfo.value.code == "codex_auth_missing"
