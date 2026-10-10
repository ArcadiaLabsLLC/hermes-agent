"""D1.05 CF-3 — a readiness build probes the Codex credential stores once, not once per persona.

``profile_readiness._provider_issue`` memoises per ``(hermes_home, auth_home,
provider, model)``, so a build over 11 persona homes that share one auth home
asked ``codex_credentials_resolvable_read_only`` 11 times, and ``load_pool``
rebuilt the pool from ``auth.json`` on each (~2.7 s on the operator's store,
plan ``design-sweep-d1-2026-10-10.md`` § D1.05). Inside
``provider_probes.provider_probe_build_scope`` (entered by the snapshot build)
the answer is memoised on ``hermes_cli.auth.authentication_owner_stamps()``.

Killing mutation: drop the memo (always call ``_codex_credentials_resolvable_now``)
-> 11 pool loads for 11 personas, not 1.

CREDENTIAL HYGIENE: every token here is an inert marker string under the
per-test sandboxed homes.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from agent_runtime import profile_readiness, provider_probes
from agent_runtime.models import AgentPersona

PROVIDER = "openai-codex"
PERSONAS = 11


def _seed_shared_auth(auth_home: Path, *, access: str = "inert-marker-singleton-access") -> Path:
    auth_home.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "credential_pool": {PROVIDER: [{
            "id": "poolslot", "label": "pool-slot", "auth_type": "oauth", "priority": 1,
            "source": "manual:device_code", "access_token": "inert-marker-pool-access",
            "refresh_token": "inert-marker-pool-refresh", "last_status": "exhausted",
            "last_status_at": time.time(), "last_error_code": None, "last_error_reset_at": None,
        }]},
        "suppressed_sources": {PROVIDER: ["device_code"]},
        "providers": {PROVIDER: {"tokens": {"access_token": access, "refresh_token": "inert-marker-refresh"},
                                 "last_refresh": "2026-09-03T14:23:54.454502Z"}},
    }
    path = auth_home / "auth.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _persona(index: int) -> AgentPersona:
    return AgentPersona(
        id=f"persona-{index:02d}", display_name=f"Persona {index}", role="worker",
        model="gpt-5.6-luna", provider=PROVIDER, api_mode=None,
        system_prompt_path="personas/p/system.md",
    )


@pytest.fixture()
def pool_loads(tmp_path, monkeypatch) -> dict[str, int]:
    from agent import credential_pool

    monkeypatch.setenv("HERMES_AUTH_HOME", str(tmp_path / "shared-auth"))
    _seed_shared_auth(tmp_path / "shared-auth")
    counts = {"load_pool": 0}
    real = credential_pool.load_pool

    def counted(provider):
        counts["load_pool"] += 1
        return real(provider)

    monkeypatch.setattr(credential_pool, "load_pool", counted)
    profile_readiness._provider_issue_cache_clear()
    yield counts
    profile_readiness._provider_issue_cache_clear()


def _readiness_over_personas(tmp_path: Path, monkeypatch) -> list:
    issues = []
    for index in range(PERSONAS):
        home = tmp_path / "homes" / f"persona-{index:02d}"
        home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("HERMES_HOME", str(home))
        issues.append(profile_readiness._provider_issue(_persona(index)))
    return issues


def test_one_build_probes_the_shared_auth_store_once_across_eleven_personas(tmp_path, monkeypatch, pool_loads):
    with provider_probes.provider_probe_build_scope():
        issues = _readiness_over_personas(tmp_path, monkeypatch)

    assert issues == [None] * PERSONAS, "the singleton can serve: every persona reads ready"
    assert pool_loads["load_pool"] == 1, (
        f"{pool_loads['load_pool']} pool loads for {PERSONAS} personas sharing one auth store"
    )


def test_without_a_build_scope_every_call_probes_live(tmp_path, monkeypatch, pool_loads):
    _readiness_over_personas(tmp_path, monkeypatch)

    assert pool_loads["load_pool"] == PERSONAS, "the memo must not outlive a build"


def test_a_credential_written_mid_build_is_probed_again(tmp_path, monkeypatch, pool_loads):
    with provider_probes.provider_probe_build_scope():
        assert provider_probes.codex_credentials_resolvable_read_only() is True
        auth = tmp_path / "shared-auth" / "auth.json"
        payload = json.loads(auth.read_text(encoding="utf-8"))
        payload["providers"] = {}
        payload["credential_pool"] = {PROVIDER: []}
        auth.write_text(json.dumps(payload), encoding="utf-8")
        os.utime(auth, ns=(9_000_000_000, 9_000_000_000))

        assert provider_probes.codex_credentials_resolvable_read_only() is False
        assert provider_probes.codex_credentials_resolvable_read_only() is False

    assert pool_loads["load_pool"] == 2


def test_the_snapshot_build_runs_inside_the_probe_scope(monkeypatch):
    from agent_runtime.snapshot import build

    seen = []

    def capture(**_kwargs):
        seen.append(provider_probes._BUILD_PROBE_MEMO.get())
        return {}

    monkeypatch.setattr(build, "_build_snapshot_in_runtime_scope", capture)
    build._build_snapshot_uncoalesced()

    assert seen and isinstance(seen[0], dict), "the snapshot build must enter provider_probe_build_scope"
    assert provider_probes._BUILD_PROBE_MEMO.get() is None, "the scope must close with the build"
