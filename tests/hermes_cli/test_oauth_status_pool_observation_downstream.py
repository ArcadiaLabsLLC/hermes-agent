"""Fork half of upstream's ``test_status_snapshot_leaves_round_robin_order_and_counts_untouched`` (lane REDS3).

The fork's round-robin position is a typed cursor in a sidecar
(``credential_rotation.json``, ``agent_runtime.pool_rotation``; MCF-44), so a runtime
``select()`` no longer rewrites ``auth.json`` and upstream's control
(``_persisted_pool(home) != before``) cannot hold. The upstream id is a strict xfail in
``tests/_downstream/id_markers/``; this asks both halves of the claim of the sidecar.
"""

from __future__ import annotations

from agent import credential_pool
from agent.credential_pool import load_pool
from hermes_cli.auth import get_codex_auth_status
from tests.hermes_cli.test_oauth_status_pool_observation import (
    _jwt_with_exp,
    _persisted_pool,
    _pool_only_codex_home,
)


def test_status_snapshot_leaves_the_rotation_cursor_and_the_pool_untouched(tmp_path, monkeypatch):
    home, _ = _pool_only_codex_home(
        tmp_path, monkeypatch, access_tokens=[_jwt_with_exp(3600), _jwt_with_exp(3600)])
    monkeypatch.setattr(credential_pool, "get_pool_strategy", lambda provider: credential_pool.STRATEGY_ROUND_ROBIN)
    sidecar = home / "credential_rotation.json"
    before = _persisted_pool(home)

    assert get_codex_auth_status()["logged_in"] is True
    assert _persisted_pool(home) == before, "a status read rotated or re-counted the persisted pool"
    assert not sidecar.exists(), "a status read advanced the rotation cursor"

    # Control: a runtime selection still rotates, and persists the new position in the sidecar.
    load_pool("openai-codex").select()
    assert sidecar.exists(), "a runtime selection wrote no rotation cursor"
