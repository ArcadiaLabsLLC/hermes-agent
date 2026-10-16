"""Fork-owned tests moved out of ``tests/hermes_cli/test_nous_inference_url_validation.py`` (lane CARRY)
and ``tests/hermes_cli/test_auth_nous_provider.py`` (lane pb-t1).

Same names, same bodies; neither upstream file carries a fork test (the roundtrip O_CREAT spy in
``test_auth_nous_provider.py`` is the held upstream PR #121225).
"""

from __future__ import annotations

import json

import pytest

from tests.hermes_cli import test_nous_inference_url_validation as _upstream
from tests.hermes_cli.test_auth_nous_provider import _future_iso, _invoke_jwt


class TestCallSiteWiring:
    # upstream's source reader, imported by name (one reader, not a copy)
    _read_auth_source = _upstream.TestCallSiteWiring._read_auth_source

    def _auth_tree(self):
        import ast
        return ast.parse(self._read_auth_source())

    @staticmethod
    def _callee_name(node):
        import ast
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    @classmethod
    def _reads_inference_base_url(cls, node):
        """True when ``node`` is ``_optional_base_url(<x>.get("inference_base_url"))``."""
        import ast
        if cls._callee_name(node) != "_optional_base_url":
            return False
        for arg in node.args:
            if not isinstance(arg, ast.Call) or cls._callee_name(arg) != "get":
                continue
            if arg.args and isinstance(arg.args[0], ast.Constant):
                if arg.args[0].value == "inference_base_url":
                    return True
        return False

    def test_no_unvalidated_inference_base_url_assignments_remain(self):
        """Every network read of ``inference_base_url`` is wrapped by the validator.

        DERIVED, not enumerated. The previous version of this test listed two
        exact byte strings - ``refreshed.get(...)`` and ``mint_payload.get(...)``
        - and asserted neither appeared. It passed for as long as it existed
        while `_nous_device_code_login` persisted the device-code poll response
        through `_optional_base_url` alone, because that site reads
        ``token_data``, which neither needle named. One of the two needles,
        ``mint_payload``, had ZERO occurrences in the whole 8,900-line file, so
        that half could never fail at all.

        The rule is structural: a ``_optional_base_url(x.get("inference_base_url"))``
        call is only safe when it is the DIRECT ARGUMENT of
        ``_validate_nous_inference_url_from_network``. That admits the nested
        form the shared-merge path already uses, and refuses a bare one
        wherever it appears and whatever the payload variable is called.
        """
        import ast
        tree = self._auth_tree()

        wrapped = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and self._callee_name(node) == (
                "_validate_nous_inference_url_from_network"
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Call) and self._reads_inference_base_url(arg):
                        wrapped.add((arg.lineno, arg.col_offset))

        reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and self._reads_inference_base_url(node)
        ]
        # Anti-vacuity: a walk that resolves nothing must say so rather than
        # report a clean tree. If this floor trips, the shape moved and the
        # gate is blind again - which is the whole failure being retired here.
        assert reads, (
            "found no _optional_base_url(...inference_base_url...) reads at all; "
            "the call shape changed and this gate can no longer see its subject"
        )

        offenders = sorted(
            node.lineno
            for node in reads
            if (node.lineno, node.col_offset) not in wrapped
        )
        assert offenders == [], (
            "unvalidated network read of inference_base_url at auth.py line(s) "
            f"{offenders}. Wrap it in _validate_nous_inference_url_from_network(): "
            "a poisoned value here redirects every subsequent proxy request, "
            "bearing the user's inference JWT, to whatever host the network said."
        )

    def test_validator_wired_at_all_known_call_sites(self):
        """Keep all four protected sources after upstream extracts refresh healing."""
        import ast
        tree = self._auth_tree()
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        direct = [n for n in calls if self._callee_name(n) == "_validate_nous_inference_url_from_network"]
        healed = [n for n in calls if self._callee_name(n) == "_healed_nous_inference_url"]
        helper = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_healed_nous_inference_url")
        assert any(isinstance(n, ast.Call) and self._callee_name(n) == "_validate_nous_inference_url_from_network" for n in ast.walk(helper))
        # One validator call is the shared helper itself, not a network source.
        assert len(direct) - 1 + len(healed) >= 4
        assert len(healed) >= 2

    def test_proxy_adapter_also_validates(self):
        """The Nous proxy adapter applies the validator as defense-in-depth
        even though auth.py already validates at the source, so a future
        bypass at the source layer still gets caught at the forward
        boundary."""
        from pathlib import Path
        import hermes_cli.proxy.adapters.nous_portal as _nous_adapter
        source = Path(_nous_adapter.__file__).read_text(encoding="utf-8")
        assert "_validate_nous_inference_url_from_network" in source


# =============================================================================
# Device-code login: the portal-provided inference URL passes the same allowlist as refresh
# =============================================================================


def _run_device_login_with_portal_inference_url(monkeypatch, portal_inference_url):
    import hermes_cli.auth as auth

    monkeypatch.delenv("NOUS_INFERENCE_BASE_URL", raising=False)
    monkeypatch.setattr(auth, "_request_device_code", lambda **kw: {
        "verification_uri_complete": "https://portal.example/device?code=ABCD",
        "user_code": "ABCD-1234", "device_code": "dev", "expires_in": 600, "interval": 5})
    monkeypatch.setattr(auth, "_poll_for_token", lambda **kw: {
        "access_token": "t", "scope": "inference:invoke", "expires_in": 3600,
        "inference_base_url": portal_inference_url})
    monkeypatch.setattr(auth, "refresh_nous_oauth_from_state", lambda state, **kw: state)
    return auth._nous_device_code_login(open_browser=False, on_verification=lambda url, code: None)


def test_device_login_refuses_portal_inference_url_outside_allowlist(monkeypatch):
    from hermes_cli.auth import PROVIDER_REGISTRY

    state = _run_device_login_with_portal_inference_url(monkeypatch, "https://attacker.example.com/v1")
    assert state["inference_base_url"] == PROVIDER_REGISTRY["nous"].inference_base_url.rstrip("/")


def test_device_login_refuses_non_https_portal_inference_url(monkeypatch):
    from hermes_cli.auth import PROVIDER_REGISTRY

    state = _run_device_login_with_portal_inference_url(
        monkeypatch, "http://inference-api.nousresearch.com/v1")
    assert state["inference_base_url"] == PROVIDER_REGISTRY["nous"].inference_base_url.rstrip("/")


def test_device_login_keeps_allowlisted_portal_inference_url(monkeypatch):
    state = _run_device_login_with_portal_inference_url(
        monkeypatch, "https://inference-api.nousresearch.com/v2/")
    assert state["inference_base_url"] == "https://inference-api.nousresearch.com/v2"


# =============================================================================
# A persisted inference URL is healed at hydration, not only at fresh admission
# =============================================================================

_FOREIGN_INFERENCE_URL = "https://attacker.example.com/v1"
_OPERATOR_INFERENCE_URL = "https://staging-inference.example.net/v1"


def _restart_and_swap_in_nous_pool_row(tmp_path, monkeypatch, persisted_url):
    """Durable state from an earlier install, then the restart path: ``load_pool("nous")`` and the
    live client's credential swap. Returns the base URL the rebuilt client would send the bearer to."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from agent.credential_pool import load_pool
    from run_agent import AIAgent

    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    token, expires_at = _invoke_jwt(seconds=3600), _future_iso(3600)
    state = {
        "portal_base_url": "https://portal.nousresearch.com",
        "inference_base_url": persisted_url, "client_id": "hermes-cli",
        "token_type": "Bearer", "scope": "inference:invoke", "access_token": token,
        "refresh_token": "refresh-tok", "expires_at": expires_at,
        "agent_key": token, "agent_key_expires_at": expires_at,
    }
    pool_row = {**state, "id": "surviving", "label": "device_code", "auth_type": "oauth",
                "priority": 0, "source": "device_code"}
    (hermes_home / "auth.json").write_text(json.dumps({
        "version": 1, "active_provider": "nous", "providers": {"nous": state},
        "credential_pool": {"nous": [pool_row]},
    }))

    entry = load_pool("nous").select()
    assert entry is not None and entry.runtime_api_key == token

    agent = SimpleNamespace(
        api_mode="chat_completions", provider="nous", model="Hermes-4-405B", api_key="old",
        base_url="https://inference-api.nousresearch.com/v1",
        _client_kwargs={"api_key": "old", "base_url": "https://inference-api.nousresearch.com/v1"},
        _reapply_route_client_config=MagicMock(), _replace_primary_openai_client=MagicMock(),
    )
    assert AIAgent._swap_credential(agent, entry) is True
    assert agent._client_kwargs["api_key"] == token
    return agent._client_kwargs["base_url"]


def test_restart_heals_persisted_foreign_nous_inference_url(tmp_path, monkeypatch):
    from hermes_cli.auth import DEFAULT_NOUS_INFERENCE_URL

    monkeypatch.delenv("NOUS_INFERENCE_BASE_URL", raising=False)
    base = _restart_and_swap_in_nous_pool_row(tmp_path, monkeypatch, _FOREIGN_INFERENCE_URL)
    assert base == DEFAULT_NOUS_INFERENCE_URL.rstrip("/")


def test_restart_keeps_persisted_allowlisted_portal_inference_url(tmp_path, monkeypatch):
    monkeypatch.delenv("NOUS_INFERENCE_BASE_URL", raising=False)
    base = _restart_and_swap_in_nous_pool_row(
        tmp_path, monkeypatch, "https://inference-api.nousresearch.com/v2")
    assert base == "https://inference-api.nousresearch.com/v2"


def test_restart_keeps_persisted_url_matching_operator_override(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_INFERENCE_BASE_URL", _OPERATOR_INFERENCE_URL)
    base = _restart_and_swap_in_nous_pool_row(tmp_path, monkeypatch, _OPERATOR_INFERENCE_URL)
    assert base == _OPERATOR_INFERENCE_URL


@pytest.mark.parametrize("persisted_url", ["https://[", "https://[::1/v1"])
def test_restart_heals_persisted_parser_invalid_nous_inference_url(
        tmp_path, monkeypatch, persisted_url):
    """A persisted value ``urlparse`` raises on is rejected by the validator; the healer must
    retire it (provider record AND pool row) instead of raising while logging it."""
    from hermes_cli.auth import DEFAULT_NOUS_INFERENCE_URL

    monkeypatch.delenv("NOUS_INFERENCE_BASE_URL", raising=False)
    base = _restart_and_swap_in_nous_pool_row(tmp_path, monkeypatch, persisted_url)
    assert base == DEFAULT_NOUS_INFERENCE_URL.rstrip("/")


def test_heal_parser_invalid_guest_inference_url_selects_welcome_host(monkeypatch):
    from hermes_cli.anon_auth import ANON_AUTH_METHOD
    from hermes_cli.auth_nous import DEFAULT_NOUS_WELCOME_URL, _heal_persisted_nous_inference_urls

    monkeypatch.delenv("NOUS_INFERENCE_BASE_URL", raising=False)
    guest = {"auth_method": ANON_AUTH_METHOD, "inference_base_url": "https://["}
    store = {"providers": {"nous": dict(guest)}, "credential_pool": {"nous": [dict(guest)]}}
    _heal_persisted_nous_inference_urls(store)
    assert store["providers"]["nous"]["inference_base_url"] == DEFAULT_NOUS_WELCOME_URL
    assert store["credential_pool"]["nous"][0]["inference_base_url"] == DEFAULT_NOUS_WELCOME_URL
