"""Fork-owned tests moved out of ``tests/agent/test_credential_pool.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

import json


def test_profile_worker_borrows_explicit_auth_home_pool(tmp_path, monkeypatch):
    profile_home = tmp_path / "hermes" / "profiles" / "worker"
    auth_home = tmp_path / "hermes" / "profiles" / "alice"
    profile_home.mkdir(parents=True, exist_ok=True)
    auth_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(profile_home))
    monkeypatch.setenv("HERMES_AUTH_HOME", str(auth_home))

    (profile_home / "auth.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
    (auth_home / "auth.json").write_text(
        json.dumps(
            {
                "version": 1,
                "credential_pool": {
                    "openai-codex": [
                        {
                            "id": "alice-codex",
                            "label": "alice-shared",
                            "auth_type": "oauth",
                            "priority": 0,
                            "source": "device_code",
                            "access_token": "shared-access-token",
                            "refresh_token": "shared-refresh-token",
                            "base_url": "https://chatgpt.com/backend-api/codex",
                        }
                    ]
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    from agent.credential_pool import load_pool

    pool = load_pool("openai-codex")
    entry = pool.select()

    assert entry is not None
    assert entry.id == "alice-codex"
    assert entry.access_token == "shared-access-token"
    assert entry.refresh_token == "shared-refresh-token"

    profile_store = json.loads((profile_home / "auth.json").read_text(encoding="utf-8"))
    assert "credential_pool" not in profile_store
