"""Phone stand-ins for the upstream functions that start a process, in modules the phone needs.

A phone cannot start a process (iOS's ``subprocess`` raises ``OSError(ENOTSUP)``; Android has no
``git``, ``ffmpeg``, shell or editor to start), yet the phone wheel keeps modules such as
``hermes_cli.config``, ``hermes_constants`` or ``tools.checkpoint_manager`` because the turn path
imports them — and each carries one to ten functions that do. Rather than an upstream door per
module, the phone entry rebinds exactly those named functions on their module to a stand-in
(owner-delegated decision D1, 2026-09-30; plan: ``docs/downstream/phone-gate-to-zero-plan-2026-09-30.md``
§2 M3, bucket D2 and lane s2-g1's carry-over). Upstream's bytes are untouched and nothing
process-wide is patched — never ``subprocess.Popen`` itself.

Each :class:`StandIn` row names a module and a function (``func`` or ``Class.method``) and says
what the phone answers instead:

* by default it raises :class:`SpawnNotAvailable` — an ``OSError`` carrying ``ENOTSUP``, the
  error iOS's ``subprocess`` itself raises, so a caller's existing ``except OSError`` degrades as
  on a device without the binary; ``error=`` mixes in the function's own documented error
  (``CommandTokenError``, ``RuntimeError`` …) where its callers catch that instead;
* ``returns=`` / ``answer=`` give the function's DOCUMENTED no-process result where it has one
  (``None`` for "could not probe", ``False`` for "nothing killed", the ``[inline-shell error: …]``
  marker, ``(False, "", reason)`` for the checkpoint store's git) — the value the real function
  returns when its spawn fails, so a turn that reaches it keeps going exactly as there.

:func:`ensure_spawn_stand_ins` is called by the embedded phone entry
(``hermes_cli/harness_parts/serve/in_memory.py``, ``EmbeddedServe.start``) and only takes effect
when the profile ships no provider SDK (``agent.provider_sdks: false`` — the phone's switch, the
same one the ``openai`` shim reads); a desktop boot never calls it, and with the switch on it does
nothing. Modules already imported are rebound at once; the rest are rebound the moment they
finish executing (an import hook), before any importer's ``from m import f`` can copy the real
function. A row whose module has no such function raises :class:`SpawnSeamStale` — the profile
gate (``scripts/bundle_profile_gate.py::spawn_seams``) imports every row's module in a child
interpreter with the phone's absences in place, so a stale name fails the gate, never skips.
"""

from __future__ import annotations

import errno
import importlib.abc
import importlib.machinery
import inspect
import subprocess
import sys
import threading
import types
from dataclasses import dataclass
from typing import Any, Callable

__layer__ = "lanes"
__all__ = ["SPAWN_STAND_INS", "SlashCommandsUnavailable", "SpawnNotAvailable", "SpawnSeamStale", "StandIn", "ensure_spawn_stand_ins",
           "install_spawn_stand_ins", "is_spawn_stand_in", "remove_spawn_stand_ins", "spawn_stand_in_of"]

#: Set on every stand-in callable: ``(module, qualname)`` of the function it replaces.
MARKER = "__hermes_spawn_stand_in__"
_RAISE = object()


class SpawnNotAvailable(OSError):
    """A function that starts a process was called on the phone, which cannot start one."""

    def __init__(self, target: str) -> None:
        super().__init__(errno.ENOTSUP, f"{target} starts a process, which is not available on the phone")
        self.target = target


class SpawnSeamStale(LookupError):
    """A stand-in row names a function its module does not have (upstream renamed or moved it)."""


@dataclass(frozen=True)
class StandIn:
    """``module.qualname`` answered on the phone; see the module docstring for the three answers."""

    module: str
    qualname: str
    returns: Any = _RAISE
    answer: Callable[..., Any] | None = None  # (the module, *args, **kwargs) -> the result
    error: type[BaseException] | str | None = None  # the documented error; a str names one on the module

    @property
    def target(self) -> str:
        return f"{self.module}.{self.qualname}"


def _stand(module: str, *qualnames: str, **how: Any) -> tuple[StandIn, ...]:
    return tuple(StandIn(module, name, **how) for name in qualnames)


def _no_process_result(_mod, cmd, *_a, **_k) -> subprocess.CompletedProcess:
    # ``_run_quiet``'s callers route a nonzero returncode to their fallback (os.walk for ``rg``,
    # the stderr text for ``git``): 127 is a shell's "command not found".
    return subprocess.CompletedProcess(cmd, 127, "", "not available on the phone: it cannot start a process")


def _hook_not_run(_mod, *_a, **_k) -> dict:
    return {"returncode": None, "stdout": "", "stderr": "", "timed_out": False, "elapsed_seconds": 0.0,
            "error": "shell hooks are not available on the phone: it cannot start a process"}


def _quick_command_error(mod, _self, _command, _exec_cmd, *_a, **_k) -> str:
    return mod.t("gateway.quick_command.error", error=SpawnNotAvailable(f"{mod.__name__} quick command"))


class SlashCommandsUnavailable(SpawnNotAvailable):
    """A typed slash command reached the phone, which runs none (owner decision D5, 2026-09-30).

    Upstream runs each one in a ``python -m tui_gateway.slash_worker`` child; the phone's controls
    are serve requests instead, so ``slash.exec`` answers this, never a second, in-process runner.
    """

    def __init__(self, target: str) -> None:
        super().__init__(target)
        self.strerror = "slash commands are unavailable on this device"
        self.args = (self.errno, self.strerror)


def _no_slash_commands(_mod, *_a, **_k):
    raise SlashCommandsUnavailable("tui_gateway.server._SlashWorker.__init__")


def _unknown_version(mod, *_a, **_k):
    return mod.VersionInfo("unknown", "unknown", None, None, None, "unknown")


#: The table: every function in a phone-kept module that starts a process (the profile gate's
#: ``subprocess_call`` rows), grouped by module.
SPAWN_STAND_INS: tuple[StandIn, ...] = (
    StandIn("agent.anthropic_adapter", "_detect_claude_code_version",
            answer=lambda mod, *_a, **_k: mod._CLAUDE_CODE_VERSION_FALLBACK),
    *_stand("agent.anthropic_credentials", "_find_claude_code_keychain_item", "_read_claude_code_keychain_payload",
            "_mirror_claude_code_credentials_to_keychain", returns=None),
    StandIn("agent.anthropic_credentials", "run_oauth_setup_token", error=FileNotFoundError),
    StandIn("agent.command_token_source", "_mint", error="CommandTokenError"),
    StandIn("agent.context_references", "_run_quiet", answer=_no_process_result),
    StandIn("agent.deadline", "kill_process_tree", returns=False),
    StandIn("agent.secret_sources.base", "run_cli", error=RuntimeError),
    StandIn("agent.secret_sources.command", "_run_helper", returns=None),
    StandIn("agent.shell_hooks", "_spawn", answer=_hook_not_run),
    StandIn("agent.skill_preprocessing", "run_inline_shell",
            returns="[inline-shell error: no shell on the phone]"),
    *_stand("gateway.platforms.base", "transcode_to_ogg_opus", "_detect_macos_system_proxy", returns=None),
    StandIn("gateway.run", "_probe_audio_duration", returns=None),
    StandIn("gateway.run_inbound", "GatewayInboundMixin._hm_run_exec_quick_command", answer=_quick_command_error),
    *_stand("gateway.run_shutdown", "GatewayShutdownMixin._spawn_windows_restart_watcher",
            "GatewayShutdownMixin._launch_detached_restart_command"),
    StandIn("gateway.slash_commands", "_spawn_detached_update"),
    StandIn("gateway.status", "terminate_pid"),
    StandIn("gateway.status", "_read_process_cmdline", returns=None),
    *_stand("hermes_cli._early_recovery", "_paths_git_wrote", "relaunch_after_restore"),
    StandIn("hermes_cli._early_recovery", "_restore_holding_claim", returns=False),
    StandIn("hermes_cli._subprocess_compat", "_user_safe_directories", answer=lambda _mod, *_a, **_k: []),
    StandIn("hermes_cli._subprocess_compat", "posix_is_zombie", returns=False),
    StandIn("hermes_cli._subprocess_compat", "_legacy_kill_process_tree", returns=None),
    StandIn("hermes_cli.config", "edit_config"),
    StandIn("hermes_cli.copilot_auth", "_probe_gh_cli_token", returns=None),
    StandIn("hermes_cli.gitlock", "_git_stdout_lines", answer=lambda _mod, *_a, **_k: []),
    StandIn("hermes_cli.gitlock", "_batch_missing_parents", answer=lambda _mod, *_a, **_k: set()),
    *_stand("hermes_cli.gitlock", "repair_broken_shallow_boundaries", "prune_stale_shallow_grafts", returns=0),
    StandIn("hermes_cli.gitlock", "_git_proc_running", returns=False),
    *_stand("hermes_cli.gitlock", "_partial_clone_filter", "fetch_full_commit_graph"),
    StandIn("hermes_cli.goals", "run_gate",
            returns=(False, -1, "[gate could not run: SpawnNotAvailable: no process on the phone]")),
    StandIn("hermes_cli.profiles", "check_alias_collision"),
    StandIn("hermes_cli.profiles", "seed_profile_skills", returns=None),
    StandIn("hermes_cli.profiles", "_cleanup_gateway_service", returns=False),
    StandIn("hermes_cli.source_check", "_git_run", returns=None),
    StandIn("hermes_cli.source_releases", "source_repository", answer=lambda mod, *_a, **_k: mod.OFFICIAL_REPOSITORY),
    StandIn("hermes_cli.source_releases", "_refuse_retirement_downgrade", error=ValueError),
    StandIn("hermes_cli.source_releases", "resolve_source_release", returns=(None, None)),
    StandIn("hermes_cli.sqlite_runtime", "probe_sqlite_runtime", returns=None),
    StandIn("hermes_cli.stderr_timestamp", "main"),
    StandIn("hermes_cli.tools_config_cua", "_run_text"),
    StandIn("hermes_cli.tools_config_cua", "_cua_driver_autostart_registered_windows", returns=False),
    StandIn("hermes_cli.version_info", "_git_version_info", answer=_unknown_version),
    StandIn("hermes_cli.version_info", "_run_git", returns=None),
    StandIn("hermes_constants", "_run_version_probe", returns=None),
    StandIn("hermes_constants_scratch", "release_git_worktrees", returns=None),
    StandIn("pm.extras", "_evaluate_in_runtime", returns=True),  # its own fallback: the resolver decides
    StandIn("pm.package", "Runner.run"),
    *_stand("tools.bot_mode_dm", "_run_local_turn", "_run_delivery"),
    StandIn("tools.checkpoint_manager", "_run_git",
            returns=(False, "", "git is not available on the phone: it cannot start a process")),
    StandIn("tools.checkpoint_manager", "_init_store",
            returns="Shadow store init failed: git is not available on the phone"),
    StandIn("tools.tts_command_provider", "run_command_provider"),
    StandIn("tools.tts_command_provider", "terminate_command_process_tree", returns=None),
    StandIn("tools.tts_tool_delivery", "_ffmpeg_run"),
    StandIn("tools.vision_tools_image_prep", "_rasterize_svg_to_png", returns=False),
    StandIn("tui_gateway.server", "_SlashWorker.__init__", answer=_no_slash_commands),
)


def is_spawn_stand_in(obj: object) -> bool:
    return spawn_stand_in_of(obj) is not None


def spawn_stand_in_of(obj: object) -> tuple[str, str] | None:
    """``(module, qualname)`` the stand-in replaces, or None for anything else."""
    if isinstance(obj, (staticmethod, classmethod)):
        obj = obj.__func__
    found = getattr(obj, MARKER, None) if isinstance(obj, types.FunctionType) else None
    return tuple(found) if isinstance(found, tuple) else None


def _error_type(row: StandIn, module: types.ModuleType) -> type[SpawnNotAvailable]:
    if row.error is None:
        return SpawnNotAvailable
    contract = getattr(module, row.error, None) if isinstance(row.error, str) else row.error
    if not (isinstance(contract, type) and issubclass(contract, BaseException)):
        raise SpawnSeamStale(f"{row.target}: its documented error {row.error!r} is not an exception class there")
    return type(f"SpawnNotAvailable_{contract.__name__}", (SpawnNotAvailable, contract),
                {"__module__": __name__})


def _stand_in(row: StandIn, module: types.ModuleType, original: Callable[..., Any]) -> Callable[..., Any]:
    error = _error_type(row, module)

    def answer(*args: Any, **kwargs: Any) -> Any:
        if row.answer is not None:
            return row.answer(module, *args, **kwargs)
        if row.returns is not _RAISE:
            return row.returns
        raise error(row.target)

    if inspect.iscoroutinefunction(original):
        async def stand_in(*args: Any, **kwargs: Any) -> Any:
            return answer(*args, **kwargs)
    else:
        def stand_in(*args: Any, **kwargs: Any) -> Any:
            return answer(*args, **kwargs)
    stand_in.__name__ = original.__name__
    stand_in.__qualname__ = original.__qualname__
    stand_in.__doc__ = f"Phone stand-in for {row.target}: it starts a process, which a phone cannot."
    stand_in.__wrapped__ = original
    setattr(stand_in, MARKER, (row.module, row.qualname))
    return stand_in


def _stand_in_owner(row: StandIn, module: types.ModuleType) -> tuple[Any, str]:
    *owners, name = row.qualname.split(".")
    owner: Any = module
    for part in owners:
        owner = getattr(owner, part, None)
        if not isinstance(owner, type):
            raise SpawnSeamStale(f"{row.target}: {part!r} is not a class in {row.module}")
    return owner, name


def _rebind(row: StandIn, module: types.ModuleType) -> None:
    owner, name = _stand_in_owner(row, module)
    raw = vars(owner).get(name)
    if is_spawn_stand_in(raw):
        return
    wrapper = type(raw) if isinstance(raw, (staticmethod, classmethod)) else None
    function = raw.__func__ if wrapper else raw
    if not isinstance(function, types.FunctionType):
        raise SpawnSeamStale(f"{row.target}: {row.module} defines no function {row.qualname!r}")
    stand_in = _stand_in(row, module, function)
    setattr(owner, name, wrapper(stand_in) if wrapper else stand_in)


class _RebindingLoader(importlib.abc.Loader):
    """The module's own loader, then the rows for it — before the import statement returns."""

    def __init__(self, loader: importlib.abc.Loader, rows: tuple[StandIn, ...]) -> None:
        self._loader, self._rows = loader, rows

    def create_module(self, spec):
        return self._loader.create_module(spec)

    def exec_module(self, module) -> None:
        self._loader.exec_module(module)
        for row in self._rows:
            _rebind(row, module)

    def __getattr__(self, name: str):  # get_source, is_package, get_resource_reader, …
        return getattr(self._loader, name)


class _RebindOnImport(importlib.abc.MetaPathFinder):
    def __init__(self, rows: dict[str, tuple[StandIn, ...]]) -> None:
        self.rows = rows

    def find_spec(self, name, path=None, target=None):
        rows = self.rows.get(name)
        if rows is None:
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(name, path, target)
            if spec is not None:
                if spec.loader is not None and hasattr(spec.loader, "exec_module"):
                    spec.loader = _RebindingLoader(spec.loader, rows)
                return spec
        return None


_LOCK = threading.Lock()
_FINDER: _RebindOnImport | None = None


def install_spawn_stand_ins(table: tuple[StandIn, ...] = SPAWN_STAND_INS) -> tuple[str, ...]:
    """Rebind every row: now for an imported module, on import for the rest. Returns the targets.

    Unconditional — the phone entry reaches it through :func:`ensure_spawn_stand_ins`. Raises
    :class:`SpawnSeamStale` for a row naming a function its (imported) module lacks.
    """
    global _FINDER
    by_module: dict[str, tuple[StandIn, ...]] = {}
    for row in table:
        by_module[row.module] = (*by_module.get(row.module, ()), row)
    with _LOCK:
        for name, rows in by_module.items():
            loaded = sys.modules.get(name)
            if loaded is not None:
                for row in rows:
                    _rebind(row, loaded)
        if _FINDER is None:
            _FINDER = _RebindOnImport({})
            sys.meta_path.insert(0, _FINDER)
        for name, rows in by_module.items():
            merged = {row.qualname: row for row in (*_FINDER.rows.get(name, ()), *rows)}
            _FINDER.rows[name] = tuple(merged.values())
    return tuple(row.target for row in table)


def remove_spawn_stand_ins(table: tuple[StandIn, ...] = SPAWN_STAND_INS) -> None:
    """Undo :func:`install_spawn_stand_ins` for ``table`` (tests; a phone never removes them)."""
    global _FINDER
    with _LOCK:
        for row in table:
            if _FINDER is not None and row.module in _FINDER.rows:
                kept = tuple(r for r in _FINDER.rows[row.module] if r.qualname != row.qualname)
                _FINDER.rows[row.module] = kept
                if not kept:
                    del _FINDER.rows[row.module]
            module = sys.modules.get(row.module)
            if module is None:
                continue
            owner, name = _stand_in_owner(row, module)
            raw = vars(owner).get(name)
            if is_spawn_stand_in(raw):
                wrapper = type(raw) if isinstance(raw, (staticmethod, classmethod)) else None
                original = (raw.__func__ if wrapper else raw).__wrapped__
                setattr(owner, name, wrapper(original) if wrapper else original)
        if _FINDER is not None and not _FINDER.rows:
            sys.meta_path.remove(_FINDER)
            _FINDER = None


def ensure_spawn_stand_ins(table: tuple[StandIn, ...] | None = None) -> tuple[str, ...]:
    """The phone entry's call: install the table when this profile ships no provider SDK."""
    from agent.transports.httpx_client import provider_sdks_enabled

    if provider_sdks_enabled():
        return ()
    return install_spawn_stand_ins(SPAWN_STAND_INS if table is None else table)
