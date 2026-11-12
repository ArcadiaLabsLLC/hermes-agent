"""What a harness process sets up before it does anything: the start-time migrations and four process globals.

Moved out of ``plugins/eternia-harness/__init__.py::register`` (``RT-HARNESS-PARSER-PLUGIN-LOAD-TWICE``) so
the two callers share one function: the plugin's ``register(ctx)`` and ``hermes_cli.harness._harness_entry``,
which runs it before a ``hermes harness`` verb's handler. None of it is registered on a plugin context, so
unloading the plugin undoes none of it.

The ``harness`` command line is built from ``plugin.yaml``'s ``setup:`` row with no plugin load, so a verb no
longer gets this work as a side effect of the parse: ``_harness_entry`` asks for it, and ``--help`` or a
mistyped verb runs none of it. The migrations run ONCE per process for one set of stores
(:func:`_stores_key`): a ``harness serve`` runs them before its verb and its post-ready plugin discovery
calls ``register(ctx)`` without repeating them. The four globals are idempotent on their own and run on
every call (a test that resets ``toolsets.TOOLSETS`` and registers again gets ``harness_core`` back).
Pinned by ``tests/hermes_cli/test_harness_start_time_setup.py``.
"""

from __future__ import annotations

import logging
import os
import threading

__layer__ = "wiring"
__all__ = ["run_start_time_setup"]


def migrate_retired_local_llama_id() -> None:
    """Owner 2026-09-29: the one-shot startup rewrite of ``local-llama-hermes`` -> ``llamacpp``
    across every store and the user's config.yaml, per home (a marker makes it one-shot)."""
    try:
        from agent_runtime.local_llama_adapter.legacy_id_migration import migrate_retired_provider_id_once

        migrate_retired_provider_id_once()
    except Exception:  # a failed migration must not take plugin load down
        logging.getLogger(__name__).warning("local llama retired-id migration failed", exc_info=True)


def migrate_legacy_persona_toolsets() -> None:
    """Ruling R2 (tool-visibility split, 2026-10-08): strip the deleted persona-level
    ``toolsets`` key from store rows once per store (a marker makes it one-shot), and from
    the root and every profile ``config.yaml`` (idempotent, every start)."""
    try:
        from agent_runtime.persona_toolsets_migration import (
            migrate_legacy_persona_toolsets_once,
            strip_legacy_persona_toolsets_from_configs,
        )

        migrate_legacy_persona_toolsets_once()
        strip_legacy_persona_toolsets_from_configs()
    except Exception:  # a failed migration must not take plugin load down
        logging.getLogger(__name__).warning("persona toolsets legacy-key migration failed", exc_info=True)


def retire_legacy_harness_blocks() -> None:
    """RT-RETIRE-LEGACY-TOP-LEVEL (old schema: delete and report): the top-level
    ``remote_gateway.*`` / ``charsheet.*`` keys move under the plugin's settings and are
    deleted from the root and every profile ``config.yaml`` (idempotent, every start)."""
    try:
        from agent_runtime.harness_settings_legacy import retire_legacy_harness_blocks as retire

        retire()
    except Exception:  # a failed migration must not take plugin load down
        logging.getLogger(__name__).warning("harness legacy-key retirement failed", exc_info=True)


def retire_persona_assignment_store() -> None:
    """RT-FULL-PERSONAASSIGNMENTSTORE: the retired assignment store's residual rows move,
    bytes intact, into ``persona_assignments_archive/retired_store/`` with a report."""
    try:
        from agent_runtime.persona_assignments import retire_persona_assignment_store as retire

        retire()
    except Exception:  # a failed migration must not take plugin load down
        logging.getLogger(__name__).warning("persona assignment store retirement failed", exc_info=True)


def migrate_legacy_office_schema() -> None:
    """Owner rule 2026-09-18 (old schema: delete and report): the one-shot office
    cleanups in ``agent_runtime.office_legacy_migration.STEPS``, once per store."""
    try:
        from agent_runtime.office_legacy_migration import run_office_legacy_migrations_once

        run_office_legacy_migrations_once()
    except Exception:  # a failed migration must not take plugin load down
        logging.getLogger(__name__).warning("office legacy-schema migration failed", exc_info=True)


def migrate_shared_character_assignments() -> None:
    """Move provable legacy choices through the agent record owner once."""
    try:
        from agent_runtime.character_assignment_migration import migrate_authored_character_assignments

        report = migrate_authored_character_assignments()
        if report.get("error"):
            logging.getLogger(__name__).warning("character assignment migration held: %s", report["error"])
        elif report["migrated"]:
            logging.getLogger(__name__).info("character assignment migration: %s", report)
    except Exception:  # retain all unmigrated choices; a migration cannot prevent startup
        logging.getLogger(__name__).warning("character assignment migration failed", exc_info=True)


def seed_persona_profile_defaults() -> None:
    """Owner ruling 2026-10-03: hermes fills the approved seed keys into every persona's
    bound profile ``config.yaml`` — absent keys only (``agent_runtime.persona_seed_defaults``)."""
    try:
        from agent_runtime.persona_seed_defaults import seed_all_persona_profiles

        seed_all_persona_profiles()
    except Exception:  # a failed seed must not take plugin load down
        logging.getLogger(__name__).warning("persona seed defaults failed", exc_info=True)


def _worker_config_frozen() -> bool:
    """A worker bound to an explicit config snapshot (upstream ``agent.safe_worker_policy``)
    reads no profile ``config.yaml``, so plugin load runs none of the config-file migrations."""
    try:
        from agent.safe_worker_policy import worker_config_snapshot
    except ImportError:  # a tree without upstream's worker policy has no frozen workers
        return False
    return worker_config_snapshot() is not None


def _compute_worker() -> bool:
    """A self-registered daemon worker (upstream ``agent.runtime_session_store``) is compute-only
    and never opens the canonical ``state.db``; the owner process runs the startup migrations."""
    try:
        from agent.runtime_session_store import is_worker_process
    except ImportError:  # a tree without upstream's worker store has no compute workers
        return False
    return is_worker_process()


_MIGRATED: set[tuple] = set()
_MIGRATED_LOCK = threading.Lock()


def _stores_key(config_frozen: bool, compute_worker: bool) -> tuple | None:
    """What the migrations read and rewrite, as this process resolves it NOW: the profile home, the head
    home, the pinned store root, and the two worker facts that pick which migrations run. None when a
    home cannot be resolved — the migrations then run unguarded, as they did at every plugin load."""
    try:
        from agent_runtime.profile_context import RUNTIME_ROOT_ENV
        from agent_runtime.profile_home import get_hermes_head_home
        from hermes_constants import get_hermes_home

        return (str(get_hermes_home()), str(get_hermes_head_home()), os.environ.get(RUNTIME_ROOT_ENV, ""),
                config_frozen, compute_worker)
    except Exception:
        return None


def _run_start_time_migrations() -> None:
    config_frozen, compute_worker = _worker_config_frozen(), _compute_worker()
    key = _stores_key(config_frozen, compute_worker)
    with _MIGRATED_LOCK:  # held across the run: a second caller waits for the first one's migrations
        if key is not None and key in _MIGRATED:
            return
        if not config_frozen:  # the three read and rewrite profile config.yaml files
            if not compute_worker:  # it also rewrites canonical state.db, which a worker never opens
                migrate_retired_local_llama_id()
            migrate_legacy_persona_toolsets()
            retire_legacy_harness_blocks()
            seed_persona_profile_defaults()
        migrate_legacy_office_schema()  # a store migration, not a config.yaml rewrite
        migrate_shared_character_assignments()
        retire_persona_assignment_store()  # a store migration too: archive the retired store's rows
        if key is not None:
            _MIGRATED.add(key)


def run_start_time_setup() -> None:
    """Bind the door, run the start-time migrations (once per process and set of stores), and install
    the three other process globals."""
    from hermes_cli.harness_parts.mission_chat_door_binding import bind_mission_chat_door

    bind_mission_chat_door()  # ruling Q10: the runtime's door onto the CLI turn handler
    _run_start_time_migrations()
    from agent_runtime.harness_toolset import ensure_harness_core

    ensure_harness_core()  # the persona lane's composite, through upstream's create_custom_toolset
    from agent_runtime.running_work.process_presence import install_process_presence

    install_process_presence()  # RT-EMIT-RUNNING-WORK-CHAT: process spawn/exit -> running_work events
    from agent_runtime.guardrail_mcp_names import add_registry_spelled_filesystem_reads

    add_registry_spelled_filesystem_reads()  # the no-progress guard reads mcp__filesystem__* names
