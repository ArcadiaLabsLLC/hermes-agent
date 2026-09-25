"""The usage-lane vocabulary and detection: which providers have a lane, and which the operator is signed in to.
"""

from __future__ import annotations

from typing import Optional


__layer__ = "policy"
__all__ = [
    "DEFAULT_USAGE_TIMEOUT",
    "USAGE_SCHEMA",
    "UnknownUsageLaneError",
    "_USAGE_LANE_PROVIDERS",
    "_codex_usage_login_detected",
    "_detect_usage_candidates",
    "_openrouter_usage_login_detected",
    "_resolve_active_provider_id",
    "_usage_failure_reason",
    "_usage_lane_detected",
    "_usage_lane_scope",
    "_usage_provider_label",
]

# --- `hermes harness usage` (account-usage lanes) contract ---------------------
# Typed per-provider account-limit snapshot the Launcher's Mission Control
# console consumes instead of scraping the human /usage text. v1 envelope is
# emitted next to `providers`; the same failure-isolation discipline applies —
# nothing in `_cmd_usage` may raise (worst case: envelope with empty lanes).
USAGE_SCHEMA = "hermes.account_usage/v1"
DEFAULT_USAGE_TIMEOUT = 20.0
# Candidate lanes, in stable emission order. A lane is only emitted when the
# operator is detected as signed-in / holding credentials for that provider.
_USAGE_LANE_PROVIDERS: tuple[str, ...] = (
    "openai-codex",
    "anthropic",
    "openrouter",
    "nous",
)


# --- `hermes harness usage` implementation ------------------------------------
#
# Structure mirrors build_provider_visibility: every seam is failure-isolated so
# a broken probe on one provider can NEVER sink the envelope or another lane.
# The reusable fetch/render primitives live upstream in agent/account_usage.py
# (which this module must not modify) — snapshot → dict serialization lives HERE.


def _usage_provider_label(provider_id: str) -> str:
    """Human display name for a provider id, degrading to the id itself."""
    try:
        from hermes_cli.models import provider_label

        return provider_label(provider_id)
    except Exception:
        return provider_id


def _resolve_active_provider_id() -> Optional[str]:
    """Normalized effective provider id, mirroring the CLI runtime resolution
    seam (`hermes_cli/status.py::_effective_provider_label`) but emitting the id
    rather than a label. Fail-open → None; ``auto`` (unresolved) also maps to
    None so callers get a concrete id or nothing.
    """
    try:
        from hermes_cli.auth import AuthError, resolve_provider
        from hermes_cli.runtime_provider import resolve_requested_provider

        requested = resolve_requested_provider()
        try:
            effective = resolve_provider(requested)
        except AuthError:
            effective = requested or None
        normalized = str(effective or "").strip().lower() or None
        if normalized in {"", "auto"}:
            return None
        return normalized
    except Exception:
        return None


def _codex_usage_login_detected() -> bool:
    """Codex lane detected when the OAuth status is logged-in OR the credential
    pool holds any openai-codex entry.

    Two independent sources OR'd together, so a raise from the FIRST is not yet
    an answer — the pool may still say yes, and that yes is the truth. But a
    raise that ends with no affirmative source is NOT "not signed in": it is
    "we could not tell", and per EG-6.1 that must reach the caller as a class,
    not as a ``False`` indistinguishable from an empty pool. So the primary
    error is held and re-raised only if nothing affirms; a raise from the pool
    read itself propagates directly (one lane carries one named class).
    """
    primary_error: Optional[BaseException] = None
    try:
        from hermes_cli.auth import get_codex_auth_status

        if bool((get_codex_auth_status() or {}).get("logged_in")):
            return True
    except Exception as exc:  # noqa: BLE001 — held, re-raised only if unanswered
        primary_error = exc
    from agent.credential_pool import load_pool

    if load_pool("openai-codex").entries():
        return True
    if primary_error is not None:
        raise primary_error
    return False


def _openrouter_usage_login_detected() -> bool:
    """OpenRouter lane detected when the pool holds an entry OR the runtime
    resolver finds a usable key.

    Same held-primary-error discipline as [_codex_usage_login_detected]: a
    failure that leaves the question unanswered is raised, never flattened into
    the ``False`` that would silently delete the lane.
    """
    primary_error: Optional[BaseException] = None
    try:
        from agent.credential_pool import load_pool

        if load_pool("openrouter").entries():
            return True
    except Exception as exc:  # noqa: BLE001 — held, re-raised only if unanswered
        primary_error = exc
    from hermes_cli.runtime_provider import resolve_runtime_provider

    runtime = resolve_runtime_provider(requested="openrouter")
    if str(runtime.get("api_key", "") or "").strip():
        return True
    if primary_error is not None:
        raise primary_error
    return False


def _usage_lane_detected(provider_id: str) -> bool:
    """True iff the operator is signed-in / holds credentials for ``provider_id``.

    Detection has THREE outcomes, not two, and EG-6.1 stopped collapsing two of
    them together:

    * ``True``  — signed in; the lane is fetched and emitted;
    * ``False`` — credentials genuinely absent; the lane is OMITTED (this is now
      the exclusive meaning of an omitted lane);
    * RAISE     — the detector could not tell. This function no longer swallows.
      [_detect_usage_candidates] catches it per provider and the lane IS emitted,
      unavailable, naming the exception class.

    The old blanket ``except Exception: return False`` was strictly worse than
    the S1 defect it neighbours: S1 left a row saying "no usage data", whereas a
    swallowed detector fault made the row VANISH from the Limits panel, leaving
    nothing to carry a reason at all.
    """
    if provider_id == "openai-codex":
        return _codex_usage_login_detected()
    if provider_id == "anthropic":
        from agent.anthropic_credentials import resolve_anthropic_token

        return bool((resolve_anthropic_token() or "").strip())
    if provider_id == "openrouter":
        return _openrouter_usage_login_detected()
    if provider_id == "nous":
        from hermes_cli.auth import get_provider_auth_state

        tok = (get_provider_auth_state("nous") or {}).get("access_token")
        return bool(isinstance(tok, str) and tok.strip())
    return False


class UnknownUsageLaneError(LookupError):
    """``_fetch_usage_lane`` was handed a provider id it has no fetcher for.

    The dispatch below covers ``_USAGE_LANE_PROVIDERS`` exactly, and that tuple
    is the ONLY producer of ids (``_detect_usage_candidates`` filters it and
    never adds). So this is unreachable today — and it is raised rather than
    handled precisely so it STAYS that way: a fifth provider added to the tuple
    without its fetcher becomes a loud, named per-lane failure instead of
    silently falling back into the upstream blanket swallow (see the docstring
    below for why that fallback was the loaded gun EG-0.3 removed).

    Carries ``provider_id`` as an attribute so ``_usage_failure_reason`` can
    name the id without ever touching ``str(exc)``.
    """

    def __init__(self, provider_id: str) -> None:
        self.provider_id = str(provider_id)
        super().__init__(f"no account-usage fetcher for lane {self.provider_id!r}")


def _usage_failure_reason(exc: BaseException, *, phase: str = "fetch") -> str:
    """The operator-facing reason for a raised usage lane, in one grammar:
    ``usage <phase> failed (<fact>)``.

    ``phase`` names WHICH half of the lane raised — ``fetch`` (the default, the
    only phase before EG-6.1) or ``detection``. It is a caller-supplied literal,
    never derived from the exception, so it cannot leak anything; and it is
    deliberately the SAME function rather than a sibling, because the
    class-name-only rule below is the whole point and a second reason-builder
    would be a second place to forget it.

    CLASS NAME ONLY for everything except an HTTP status error, where the bare
    numeric status is added — a status code leaks nothing (no token, no URL, no
    exception message), and it is the single fact that separates "the provider
    rejected our credential" from "the network broke". 401/403 additionally
    earn the re-auth hint, matching the reauth-vs-connectivity discipline: only
    a confirmed auth rejection may suggest signing in again.

    ``UnknownUsageLaneError`` earns the second such exemption, on the same test
    the HTTP status passes: the fact added is the provider ID, which is the
    dispatch key itself — already carried verbatim in this lane's ``provider``
    field — so it leaks nothing that is not already in the envelope, and it is
    the single fact that turns "a lane failed" into "lane X has no fetcher".
    Read off ``exc.provider_id``, never ``str(exc)``.
    """
    name = type(exc).__name__
    if isinstance(exc, UnknownUsageLaneError):
        return f"usage {phase} failed ({name}: {exc.provider_id})"
    status = None
    response = getattr(exc, "response", None)
    if response is not None:
        raw = getattr(response, "status_code", None)
        if isinstance(raw, int):
            status = raw
    if status is None or name != "HTTPStatusError":
        return f"usage {phase} failed ({name})"
    suffix = " — re-auth may be required" if status in (401, 403) else ""
    return f"usage {phase} failed (HTTP {status}{suffix})"


def _usage_lane_scope(only_provider: Optional[str]) -> tuple[str, ...]:
    """The lanes this invocation may speak about, in stable emission order —
    ``_USAGE_LANE_PROVIDERS`` narrowed by ``--provider``. FILTER ONLY: it never
    adds an id, which is the property [UnknownUsageLaneError] leans on."""
    providers = _USAGE_LANE_PROVIDERS
    if only_provider:
        norm = str(only_provider).strip().lower()
        providers = tuple(p for p in providers if p == norm)
    return providers


def _detect_usage_candidates(
    only_provider: Optional[str],
) -> tuple[list[str], dict[str, str]]:
    """``(detected, detect_failures)`` — the two-value split EG-6.1 introduced.

    ``detected`` are the lanes to fetch. ``detect_failures`` maps provider id →
    the operator-facing reason for a detector that RAISED, so
    [build_account_usage] can emit that lane unavailable-and-named instead of
    letting it vanish. Isolation is per provider: one broken detector never
    suppresses another lane, which is the same guarantee
    [_fetch_usage_lanes] already gives the fetch half.
    """
    detected: list[str] = []
    failures: dict[str, str] = {}
    for provider in _usage_lane_scope(only_provider):
        try:
            hit = _usage_lane_detected(provider)
        except Exception as exc:  # noqa: BLE001 — class/status only, per lane
            failures[provider] = _usage_failure_reason(exc, phase="detection")
            continue
        if hit:
            detected.append(provider)
    return detected, failures
