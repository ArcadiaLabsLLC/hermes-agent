"""The harness verbs' doors onto upstream internals: every ``_private`` upstream name a part reaches.

Program ruling Q5 (god-file-program-2026-09-24.md §6, §9): one adapter per fork
package. A harness part that needs a private upstream name calls the door here
instead of importing it, so the surface a weekly upstream merge can break for
the harness is THIS file — W0-G6's ``private_upstream_imports`` rows for
``harness_parts`` all live in it, and a merge that renames one names this
module in its failure.

Each door imports its upstream name at CALL time, exactly as the call sites it
replaces did: a verb that never needs a reader never pays its import, and a
test stub on the upstream module (``agent.account_usage``, ``hermes_cli.status``,
…) still reaches the call. Each door names its class from the second-door rule
(``docs/agent-runtime-harness/planned/second-doors-2026-09-24.md``): FIRST — no
public door exists upstream yet and the read is read-only, so the reach stays,
named, until one does.

Layer: ``models`` — the lowest, because every layer of the harness may need an
upstream read, and a door above its caller would be an upward import (W0-G6).
"""

from __future__ import annotations

from typing import Any, Optional

__layer__ = "models"
__all__ = [
    "classify_exhausted_status",
    "configured_model_label",
    "display_source",
    "effective_provider_label",
    "exhausted_until",
    "fetch_anthropic_account_usage",
    "fetch_codex_account_usage",
    "fetch_openrouter_account_usage",
    "first_env_value",
    "format_exhausted_status",
    "load_openai_cls",
    "status_api_keys",
]


# ── credential health (`hermes auth list`'s own classification) ────────────


def exhausted_until(entry: Any) -> Optional[float]:
    """``agent.credential_pool._exhausted_until``: when an exhausted credential retries."""
    from agent.credential_pool import _exhausted_until

    return _exhausted_until(entry)


def classify_exhausted_status(entry: Any) -> tuple[str, bool]:
    """``hermes_cli.auth_commands._classify_exhausted_status``: ``(label, retryable)``."""
    from hermes_cli.auth_commands import _classify_exhausted_status

    return _classify_exhausted_status(entry)


def format_exhausted_status(entry: Any) -> str:
    """``hermes_cli.auth_commands._format_exhausted_status``: the human status suffix."""
    from hermes_cli.auth_commands import _format_exhausted_status

    return _format_exhausted_status(entry)


def display_source(source: str) -> str:
    """``hermes_cli.auth_commands._display_source``: a credential source as `auth list` shows it."""
    from hermes_cli.auth_commands import _display_source

    return _display_source(source)


# ── the status box (`hermes status`) ─────────────────────────────────────


def configured_model_label(config: dict) -> str:
    """``hermes_cli.status._configured_model_label``."""
    from hermes_cli.status import _configured_model_label

    return _configured_model_label(config)


def effective_provider_label() -> str:
    """``hermes_cli.status._effective_provider_label``."""
    from hermes_cli.status import _effective_provider_label

    return _effective_provider_label()


def first_env_value(names: Any) -> str:
    """``hermes_cli.status._first_env_value``: the first set env var of ``names``."""
    from hermes_cli.status import _first_env_value

    return _first_env_value(names)


def status_api_keys() -> dict:
    """``hermes_cli.status_auth._API_KEYS``: the status box's API-key registry, in its order."""
    from hermes_cli.status_auth import _API_KEYS

    return _API_KEYS


# ── account usage: the per-provider fetchers, around upstream's blanket swallow ──


def fetch_codex_account_usage():
    """``agent.account_usage._fetch_codex_account_usage`` — called DIRECTLY, never
    through ``fetch_account_usage``, whose blanket ``except`` erases the failure
    class (see ``usage/lanes._fetch_usage_lane``)."""
    from agent.account_usage import _fetch_codex_account_usage

    return _fetch_codex_account_usage()


def fetch_anthropic_account_usage():
    """``agent.account_usage._fetch_anthropic_account_usage`` (direct, as above)."""
    from agent.account_usage import _fetch_anthropic_account_usage

    return _fetch_anthropic_account_usage()


def fetch_openrouter_account_usage(base_url: Optional[str], api_key: Optional[str]):
    """``agent.account_usage._fetch_openrouter_account_usage`` (direct, as above)."""
    from agent.account_usage import _fetch_openrouter_account_usage

    return _fetch_openrouter_account_usage(base_url, api_key)


# ── serve boot ─────────────────────────────────────────────────────────────


def load_openai_cls() -> type:
    """``agent.process_bootstrap._load_openai_cls``: import and cache ``openai.OpenAI``."""
    from agent.process_bootstrap import _load_openai_cls

    return _load_openai_cls()
