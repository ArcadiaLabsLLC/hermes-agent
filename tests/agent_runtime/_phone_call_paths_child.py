"""Child of ``test_phone_bundle_turn_closure.py``'s call-path case: three phone call paths, run where every
first-party module outside the phone bundle's plan refuses to import and every process spawn is refused.

Not a test module (no ``test_`` prefix): the parent runs it as ``python <this file> <plan.json> <out.json>``
in a fresh interpreter, so no module the test process already imported can stand in for one the phone
lacks. ``plan.json`` holds ``modules`` (the packager's phone plan) and ``tops`` (the first-party top-level
names). The install is made the phone's: ``agent_runtime.bundled_toolsets.PHONE_PLATFORMS`` names this
platform, so the installed profile is ``bundled-phone`` (its switches, its switched-off modules).
``out.json`` gets, per case, its answer or its error, plus every refused spawn and every warning logged.
"""

from __future__ import annotations

import importlib.abc
import json
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path

PLAN, OUT = Path(sys.argv[1]), Path(sys.argv[2])
plan = json.loads(PLAN.read_text(encoding="utf-8"))
SHIPPED, TOPS = frozenset(plan["modules"]), frozenset(plan["tops"])


class OnlyThePhonePlan(importlib.abc.MetaPathFinder):
    """A first-party module the phone plan does not ship is missing, as it is in the phone bundle."""

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in TOPS and name not in SHIPPED:
            raise ModuleNotFoundError(f"No module named {name!r} (not in the phone bundle)", name=name)
        return None


sys.meta_path.insert(0, OnlyThePhonePlan())

spawns: list[list[str]] = []
_Popen = subprocess.Popen


class RefusedPopen(_Popen):
    """A phone starts no process: record the argv, refuse as the phone's spawn stand-in does."""

    def __init__(self, args, *a, **k):
        argv = [str(args)] if isinstance(args, (str, bytes, os.PathLike)) else [str(x) for x in args]
        spawns.append(argv)
        raise PermissionError(13, "Permission denied", argv[0])


subprocess.Popen = RefusedPopen

warnings: list[str] = []


class Collect(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            warnings.append(f"{record.name}: {record.getMessage()}"
                            + (f" [{record.exc_info[1]!r}]" if record.exc_info and record.exc_info[1] else ""))


logging.getLogger().addHandler(Collect())
logging.getLogger().setLevel(logging.WARNING)

from agent_runtime import bundled_toolsets  # noqa: E402

bundled_toolsets.PHONE_PLATFORMS = frozenset({*bundled_toolsets.PHONE_PLATFORMS, sys.platform})

# The phone ships a switched-off module of a scanned package in the sibling tree (``phone_forced/``,
# agent_runtime/bundle_profiles/forced_tree.py), where the tool scan never looks: here, in one checkout,
# the scan sees only what the phone's app/ holds: shipped and not switched off.
from tools import registry as _registry  # noqa: E402

_SWITCHED_OFF = bundled_toolsets.bundled_profile().switched_off_modules
_candidates = _registry._tool_module_candidates


def _scanned_on_the_phone(tools_path):
    def module(path):
        return ".".join(("tools", *path.relative_to(tools_path).with_suffix("").parts))
    return [path for path in _candidates(tools_path) if module(path) in SHIPPED
            and not any(module(path) == off or module(path).startswith(off + ".") for off in _SWITCHED_OFF)]


_registry._tool_module_candidates = _scanned_on_the_phone

results: dict[str, dict] = {}


def case(name):
    def run(fn):
        before = len(spawns)
        try:
            results[name] = {"answer": fn()}
        except BaseException as exc:  # noqa: BLE001 -- the parent judges every failure
            results[name] = {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()}
        results[name]["spawns"] = spawns[before:]
        return fn
    return run


T0 = "2026-11-21T12:00:00+00:00"
project = Path(os.environ["HERMES_HOME"]).parent / "repos" / "local" / "notes"
project.mkdir(parents=True)
(project / "TODO.md").write_text("# Notes\n- buy milk\n", encoding="utf-8")


@case("tool_call")
def _tool_call():
    """A phone agent's read_file, through the entry every tool call takes (upstream model_tools)."""
    from agent_runtime import phone_file_tools
    from agent_runtime.store import WorkspaceStore
    from agent_runtime.workspace_slots import bind, declare

    workspace = WorkspaceStore().create(name="Phone").id
    declare(workspace, [{"name": "notes", "repo": {"clone_url": None, "local": True}}], issued_at=T0, machine="m")
    bind(workspace, "notes", str(project), issued_at=T0)
    # The phone's embedded entry registers them (EmbeddedServe.start), under the installed phone profile,
    # though the plan ships upstream's file_tools (forced tree) where a presence probe would find it.
    import model_tools

    registered = phone_file_tools.ensure_phone_file_tools()
    first = json.loads(model_tools.handle_function_call("read_file", {"path": "notes/TODO.md"}))
    # The turn-end cleanup (agent.client_lifecycle forget_file_state) imports upstream's module lazily;
    # its module-level registrations must not take the four names back.
    import tools.file_tools  # noqa: F401

    again = json.loads(model_tools.handle_function_call("read_file", {"path": "notes/TODO.md"}))
    return {"registered": registered, "first": first, "after_upstreams_import": again}


@case("custom_endpoint_resume")
def _custom_endpoint_resume():
    """The identity a resumed chat on a bare custom endpoint (no ``custom_providers`` entry) asks for."""
    from hermes_cli.runtime_provider_custom import session_provider_identity

    return session_provider_identity("custom", "custom", "http://10.0.2.2:8080/v1", "qa-model")


@case("work_engine_tick")
def _work_engine_tick():
    """One tick of the serve's Work engine, with its default board sync and workspace list."""
    from types import SimpleNamespace

    from agent_runtime.default_scope import DEFAULT_WORKSPACE_ID
    from agent_runtime.work_store.engine import WorkEngine
    from agent_runtime.workspace_slots import bind, declare

    # The emulator's workspace: the default one, a project folder bound in it (a board with no brain yet,
    # whose sync asks the checkout's git common dir).
    declare(DEFAULT_WORKSPACE_ID, [{"name": "notes", "repo": {"clone_url": None, "local": True}}],
            issued_at=T0, machine="m")
    bind(DEFAULT_WORKSPACE_ID, "notes", str(project), issued_at=T0)
    executor = SimpleNamespace(on_settle=lambda _cb: None, status=lambda _run_id: None)
    return WorkEngine(executor=executor).tick()


OUT.write_text(json.dumps({"cases": results, "warnings": warnings}, default=str), encoding="utf-8")
