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
    "codex_bounded_prompt_cache_key",
    "codex_cache_scope_from_session_id",
    "codex_content_cache_key",
    "compression_threshold_for_model",
    "cron_pools_present",
    "mcp_key_name",
    "mcp_register_server_tools",
    "mcp_resolve_server_key",
    "mcp_sdk_available_flag",
    "mcp_server_map",
    "mcp_signal_reconnect",
    "mcp_wait_for_session",
    "default_hermes_home",
    "dispatch_streams",
    "doctor_section",
    "gateway_agent_pending_sentinel",
    "iter_named_profile_dirs",
    "looks_like_help_or_version_command",
    "pid_exists",
    "profile_id_pattern",
    "sanitize_surrogates",
    "profiles_root",
    "session_async_delivery_unset",
    "session_async_delivery_var",
    "skills_sync_primitives",
    "skills_tool_inspection_doors",
    "skills_walker",
    "strip_quotes",
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


def skills_tool_inspection_doors():
    """``tools.skills_tool``'s ``_find_all_skills``, ``_sort_skills``, ``_get_disabled_skill_names``,
    ``_skill_lookup_path_error``, ``_skill_search_dirs`` and ``_locate_skill`` ITSELF, in that
    order — read by ``skill_inspection.skill_inspection_reader`` (lane PF-3 moved the reader out
    of ``skills_tool.py``; it binds human inspection to the tool's own discovery and
    collision/trust gates, so a copy would be a second resolver). Held widening row: publish a
    read-only inspection port (catalog rows + locate) on upstream's skills tool."""
    from tools.skills_tool import (
        _find_all_skills, _get_disabled_skill_names, _locate_skill, _skill_lookup_path_error,
        _skill_search_dirs, _sort_skills,
    )

    return (_find_all_skills, _sort_skills, _get_disabled_skill_names, _skill_lookup_path_error,
            _skill_search_dirs, _locate_skill)


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


# ── tools.mcp_* — the MCP admission's warm-transport reads (lane B4) ────────
#
# ``agent_runtime.mcp_admission.transport`` reads eight private names across
# four upstream modules; each is read here, at CALL time, so a stub on the
# upstream module (``tools.mcp_tool._servers``, ``tools.mcp_tool_loop.
# _signal_reconnect``, …) still reaches it and a missing seam raises at the call
# the caller already guards (fail CLOSED). One held widening row per name
# (ruling Q7, ``upstream-footprint-ledger.md``).


def mcp_sdk_available_flag() -> bool:
    """``tools.mcp_tool._MCP_AVAILABLE`` — is the optional ``mcp`` client importable.
    Held widening row: publish ``mcp_sdk_available()``."""
    from tools.mcp_tool import _MCP_AVAILABLE

    return bool(_MCP_AVAILABLE)


def mcp_server_map() -> tuple[dict, object]:
    """``tools.mcp_tool._servers`` and ``._lock`` — the process's server cache and
    the lock it is read under, as a PAIR: they are only ever read together. Held
    widening rows: publish ``current_servers()``."""
    from tools.mcp_tool import _lock, _servers

    return _servers, _lock


def mcp_key_name(key: object) -> str:
    """``tools.mcp_tool_scope._key_name`` — a cache key's server name. Held
    widening row: publish ``key_name``."""
    from tools.mcp_tool_scope import _key_name

    return _key_name(key)


def mcp_resolve_server_key(name: str) -> object:
    """``tools.mcp_tool_scope._resolve_server_key`` — the current profile's cache
    key for a server name. Held widening row: publish ``resolve_server_key``."""
    from tools.mcp_tool_scope import _resolve_server_key

    return _resolve_server_key(name)


def mcp_signal_reconnect(server: object) -> object:
    """``tools.mcp_tool_loop._signal_reconnect`` — nudge a parked server. Held
    widening row: publish ``signal_reconnect``."""
    from tools.mcp_tool_loop import _signal_reconnect

    return _signal_reconnect(server)


def mcp_wait_for_session(server: object, timeout: float) -> object:
    """``tools.mcp_tool_loop._wait_for_server_session_ready`` — wait a bounded
    moment for a nudged server's session. Held widening row: publish
    ``wait_for_server_session_ready``."""
    from tools.mcp_tool_loop import _wait_for_server_session_ready

    return _wait_for_server_session_ready(server, timeout=timeout)


def mcp_register_server_tools(name: str, server: object, config: dict) -> object:
    """``tools.mcp_tool_registration._register_server_tools`` — re-register a
    connected server's tools under a run's filter (the ``tools/list_changed``
    nuke-and-repave). Held widening row: publish ``register_server_tools``."""
    from tools.mcp_tool_registration import _register_server_tools

    return _register_server_tools(name, server, config)
# ── lane W3-B: the single-reader reaches, moved in (each a held widening row in
# ``upstream-footprint-ledger.md``, "Stock files a fork module reads by private
# name"; each imported at CALL time like the call site it replaces) ──────────


def codex_bounded_prompt_cache_key(key):
    """``agent.transports.codex._bounded_prompt_cache_key`` — read by ``cache_routing``."""
    from agent.transports.codex import _bounded_prompt_cache_key

    return _bounded_prompt_cache_key(key)


def codex_cache_scope_from_session_id(session_id):
    """``agent.transports.codex._cache_scope_from_session_id`` — read by ``cache_routing``."""
    from agent.transports.codex import _cache_scope_from_session_id

    return _cache_scope_from_session_id(session_id)


def codex_content_cache_key(instructions, tools, scope):
    """``agent.transports.codex._content_cache_key`` — read by ``cache_routing``."""
    from agent.transports.codex import _content_cache_key

    return _content_cache_key(instructions, tools, scope)


def dispatch_streams(agent) -> bool:
    """``agent.turn_api_call._should_stream`` — read by ``conversation_observability``."""
    from agent.turn_api_call import _should_stream

    return bool(_should_stream(agent))


def session_async_delivery_var():
    """``gateway.session_context._SESSION_ASYNC_DELIVERY`` (the ContextVar itself) —
    read by ``delivery_capability``."""
    from gateway.session_context import _SESSION_ASYNC_DELIVERY

    return _SESSION_ASYNC_DELIVERY


def session_async_delivery_unset():
    """``gateway.session_context._UNSET`` (the sentinel) — read by ``delivery_capability``."""
    from gateway.session_context import _UNSET

    return _UNSET


def doctor_section(title: str) -> None:
    """``hermes_cli.doctor_report._section`` — read by ``doctor_extensions``."""
    from hermes_cli.doctor_report import _section

    _section(title)


def gateway_agent_pending_sentinel():
    """``gateway.run._AGENT_PENDING_SENTINEL`` — read by ``gateway_queue_status``."""
    from gateway.run import _AGENT_PENDING_SENTINEL

    return _AGENT_PENDING_SENTINEL


def profile_id_pattern():
    """``hermes_cli.profiles._PROFILE_ID_RE`` — read by ``profile_home``."""
    from hermes_cli.profiles import _PROFILE_ID_RE

    return _PROFILE_ID_RE


def iter_named_profile_dirs():
    """``hermes_cli.profiles._iter_named_profile_dirs()`` — read by ``profile_home``."""
    from hermes_cli.profiles import _iter_named_profile_dirs

    return _iter_named_profile_dirs()


def skills_sync_primitives():
    """``(tools.skills_sync._dir_hash, tools.skills_sync._read_skill_name)`` ITSELF —
    read by ``skill_publishability._sync_primitives``, which fails closed on any
    import error. Raises what the import raises."""
    from tools.skills_sync import _dir_hash, _read_skill_name

    return _dir_hash, _read_skill_name


def looks_like_help_or_version_command(command: str) -> bool:
    """``tools.terminal_tool_guards._looks_like_help_or_version_command`` — read by ``terminal_policy``."""
    from tools.terminal_tool_guards import _looks_like_help_or_version_command

    return _looks_like_help_or_version_command(command)


def strip_quotes(text: str) -> str:
    """``tools.terminal_tool_guards._strip_quotes`` — read by ``terminal_policy``."""
    from tools.terminal_tool_guards import _strip_quotes

    return _strip_quotes(text)
