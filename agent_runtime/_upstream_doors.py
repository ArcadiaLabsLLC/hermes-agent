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
    "cron_pools_present",
    "default_hermes_home",
    "pid_exists",
    "sanitize_surrogates",
    "profiles_root",
    "skills_walker",
    "terminate_host_pid",
]


def pid_exists(pid: int) -> bool:
    """``gateway.status._pid_exists`` — serve_registry, the dispatch store's
    boot sweep (``dispatch_store.delivery``) and ``running_work.ownership``'s
    PID identity read it here."""
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


def terminate_host_pid(pid: int, expected_start: int | None) -> None:
    """``tools.process_registry.ProcessRegistry._terminate_host_pid`` — the
    identity-verified tree-kill, read by
    ``tools/agent_chat_dispatch/child.py::_kill_child``. Held widening row
    (ruling Q7, ``upstream-footprint-ledger.md``): publish
    ``ProcessRegistry.terminate_host_pid``. Raises what the upstream helper
    raises; the caller is best-effort by contract."""
    from tools.process_registry import ProcessRegistry

    ProcessRegistry._terminate_host_pid(int(pid), expected_start)


def cron_pools_present(scheduler: object) -> bool:
    """``cron.scheduler._parallel_pool`` / ``._sequential_pool`` — the dispatch
    pools the ticker creates lazily on its first tick and keeps, read by
    ``running_work.lanes_process._cron_owned_here`` as durable proof the
    scheduler runs in THIS process. Private ATTRIBUTES read by ``getattr`` on
    the module the caller already holds (never imported here), so W0-G6's
    private-import arm cannot see the reach. Held widening row (ruling Q7,
    ``upstream-footprint-ledger.md``): publish ``scheduler.owns_running_jobs()``."""
    return any(
        getattr(scheduler, attr, None) is not None
        for attr in ("_parallel_pool", "_sequential_pool")
    )
