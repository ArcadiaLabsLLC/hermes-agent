"""Provider readiness and context-local non-persisting credential selection."""
from typing import Optional, Dict, Any
from agent_runtime import auth_extensions as auth_ext
from agent_runtime.pool_rotation import pool_rotation_scope

__layer__ = "stores"


def probe_runtime_provider(
    *,
    requested: Optional[str] = None,
    target_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve credentials to LEARN whether they resolve — never to spend them.

    Identical resolution to :func:`resolve_runtime_provider` (same providers,
    same order, same typed failures), with one difference: a credential-pool
    selection made here does not write the rotation cursor back to the
    credential store.

    This exists as a named function rather than a keyword at the call site on
    purpose. A read that rewrites the credential store is the same class of
    defect as a projection that records provider health while building: the
    snapshot's readiness pass reads ``auth.json`` and is NOT allowed to move it,
    because the file sits outside the build's declared input closure — a moved
    ``auth.json`` on an otherwise-quiescent store is served as a false cache HIT
    (MCF-16). Callers that intend to USE the credential must keep calling
    :func:`resolve_runtime_provider`; the persisting default is the correct one
    for them, and round-robin genuinely needs the write-back.
    """
    from hermes_cli.runtime_provider import resolve_runtime_provider
    with pool_rotation_scope(False):
        return resolve_runtime_provider(requested=requested, target_model=target_model)

def codex_credentials_resolvable_read_only() -> bool:
    """Can a Codex turn resolve a credential right now — asked without spending one.

    This is the readiness-side mirror of the ``openai-codex`` order inside
    :func:`resolve_runtime_provider`, and it lives HERE, beside that order,
    because the defect it retires is the two drifting apart. Readiness used to
    answer this question from ``load_pool("openai-codex").peek()`` alone, which
    is only the FIRST of the run path's credential sources: when the pool has
    no available entry the run path falls through to
    ``resolve_codex_runtime_credentials()`` and serves the turn from the
    singleton token set in the auth store. A pool entry inside an exhaustion
    cooldown therefore reported "Provider credential attention required" for an
    agent whose every turn was succeeding — measured 2026-09-08 against a live
    profile whose pool entry was marked exhausted at 16:45:54 while API calls
    at 16:46:06 and 16:47:47 completed normally on the singleton.

    The two sources, in the run path's order:

    1. the credential pool's own availability rules (``peek()``: cooldowns,
       dead entries, refresh needs), and
    2. the auth store the Codex client actually reads
       (:func:`agent_runtime.auth_extensions.codex_auth_store_credentials_present`).

    Attention is reported only when NEITHER can serve a turn. A genuinely dead
    lane — no pool entry with a token and no singleton/global token set — still
    reports attention, and must: this narrows a false positive, it does not
    delete the true one.

    Read-only in the MCF-16 sense, which is the reason the readiness pass was
    given a codex branch of its own in the first place: it refreshes no token,
    advances no round-robin cursor, and mints, spends and expires nothing.
    ``peek()`` takes the pool's non-clearing availability path (no
    ``clear_expired``, no ``refresh``) and the auth-store half is a read
    documented at its definition. The one write either half can still reach is
    the pre-existing re-auth resync inside ``_available_entries`` — a real
    credential change adopted from ``auth.json``, whose write is honest and was
    never this branch's to suppress.
    """

    # Resolved at call time, not bound at import: the readiness suites stand a
    # fake pool up by setting ``agent.credential_pool.load_pool``, and a
    # module-level binding would not see it.
    from agent.credential_pool import load_pool as _load_pool

    entry = _load_pool("openai-codex").peek()
    if entry is not None and (
        getattr(entry, "runtime_api_key", None)
        or getattr(entry, "access_token", None)
    ):
        return True
    return auth_ext.codex_auth_store_credentials_present()
