"""agent_runtime's doors onto upstream internals — the ``_private`` names more than one module reached.

Program ruling Q5 (god-file-program-2026-09-24.md §6, §9): one adapter per fork
package; ``hermes_cli/harness_parts/_upstream_doors.py`` is the harness's. A
private upstream name that several agent_runtime modules read is read HERE,
once, so a weekly upstream merge that renames it breaks one door instead of N
call sites, and W0-G6 carries one ``private_upstream_imports`` row for it
instead of one per reader. The single-reader reaches still in their own files
are the rest of that arm (``tests/fixtures/import_layers_grandfathered.json``);
the lane that opens such a file moves its reach here.

Each door imports its upstream name at CALL time, as every call site it
replaces did: a stub on the upstream module (``gateway.status._pid_exists``,
``hermes_cli.profiles._get_profiles_root``) still reaches the call.

Layer: ``models`` — the lowest, so every layer may use a door without an
upward import (W0-G6).
"""

from __future__ import annotations

from pathlib import Path

__layer__ = "models"
__all__ = [
    "compression_threshold_for_model",
    "default_hermes_home",
    "pid_exists",
    "sanitize_surrogates",
    "profiles_root",
    "skills_walker",
]


def pid_exists(pid: int) -> bool:
    """``gateway.status._pid_exists`` — serve_registry reads it here.

    ``dispatch_store`` and ``running_work`` still import it themselves: both are
    over the 800-line ceiling and grandfathered by W0-G1, whose GREW arm refuses
    the one line the door's import costs them. Their lanes (R1/R2) move them
    when they split those files.
    """
    from gateway.status import _pid_exists

    return _pid_exists(pid)


def profiles_root() -> Path:
    """``hermes_cli.profiles._get_profiles_root`` — read by core_cache and snapshot."""
    from hermes_cli.profiles import _get_profiles_root

    return _get_profiles_root()


def default_hermes_home() -> Path:
    """``hermes_cli.profiles._get_default_hermes_home`` — read beside ``profiles_root`` by core_cache."""
    from hermes_cli.profiles import _get_default_hermes_home

    return _get_default_hermes_home()


def compression_threshold_for_model(model: str, provider: str | None, *, allow_codex_gpt55_autoraise: bool) -> object:
    """``agent.auxiliary_client._compression_threshold_for_model`` — read by
    ``prompt_observability.context_budget``. Held widening row (ruling Q7,
    ``upstream-footprint-ledger.md``): expose it publicly."""
    from agent.auxiliary_client import _compression_threshold_for_model

    return _compression_threshold_for_model(
        model, provider, allow_codex_gpt55_autoraise=allow_codex_gpt55_autoraise
    )


def skills_walker():
    """``tools.skills_tool._find_all_skills`` ITSELF, not a wrapper — read by
    ``prompt_observability.skills_resolver``, whose installed-catalog memo keys
    on the walker's identity so a patched or reloaded walker invalidates it.
    Held widening row (ruling Q7): publish ``find_all_skills``."""
    from tools.skills_tool import _find_all_skills

    return _find_all_skills


def sanitize_surrogates(text: str) -> str:
    """``agent.message_sanitization._sanitize_surrogates`` — read by
    ``profile_runner.resident_actor._sanitized_user_message_text``. Held widening
    row (ruling Q7, ``upstream-footprint-ledger.md``): publish
    ``sanitize_surrogates``. Raises what the upstream helper raises, and
    ImportError if it relocates — the caller keeps its own fallback."""
    from agent.message_sanitization import _sanitize_surrogates

    return _sanitize_surrogates(text)
