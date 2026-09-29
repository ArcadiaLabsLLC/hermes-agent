"""Golden transport parity harness: the same ``runtime.*`` requests through the desktop serve
(stdio, daemon shell) and the embedded serve (in-memory pipe, embedded shell) produce identical
frames. Plan Stage 2 step 10.

For any P1 lane (``runtime.conversation.*``, ``runtime.chat.message``, the history seam)::

    from tests.agent_runtime.serve_transport_parity import assert_transport_parity, rpc

    def test_my_method_is_transport_blind(tmp_path, monkeypatch):
        assert_transport_parity(tmp_path, monkeypatch, [rpc("r1", "runtime.my.method", {...})],
                                seed=lambda app_dir: ...)  # optional: identical state in both roots

Each leg gets its OWN app folder (``configure_app_folder``'s layout), seeded by ``seed``, so a
write in one leg cannot feed the other; the folder path is normalized to ``<APP>``. Compared:
every frame except the process-lifecycle ones (``booting`` / ``ready`` / ``shutdown``, which
carry the shell's own blocks, the timer-driven ``busy``, and the daemon shell's registry log
lines), grouped by request id in arrival
order, with the per-process stamps (``pid``, ``boot_id``, ``starter_pid``) dropped. The ready
frames are compared by KEY SET: both shells answer every block, the embedded one with typed
``not_applicable:embedded`` values.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from hermes_cli.harness_parts.serve.in_memory import EmbeddedServe, app_folder_environment
from hermes_cli.harness_parts.serve.session import serve_loop

LIFECYCLE_EVENTS = frozenset({"booting", "ready", "shutdown", "busy"})
#: The daemon shell's own registry bookkeeping, logged as ``stderr`` line frames on a non-service
#: serve. An embedded shell advertises nothing, so it has none of these to log.
SHELL_LOG_EVENTS = frozenset({"serve_instance_unregistered", "serve_instance_unregister_failed",
                              "serve_registry_pruned", "serve_instances_pruned"})
VOLATILE_KEYS = frozenset({"pid", "boot_id", "starter_pid"})
WAIT_SECONDS = 60.0


def rpc(rid: str, method: str, params: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


def _use_app_folder(app_dir: Path, monkeypatch) -> None:
    for name, value in app_folder_environment(app_dir).items():
        Path(value).mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, value)


def _lines(requests: Iterable[Any]) -> list[str]:
    return [(r if isinstance(r, str) else json.dumps(r)).rstrip("\n") + "\n" for r in requests]


def run_stdio(requests, app_dir: Path, monkeypatch, **options) -> list[dict]:
    """The desktop serve: ``serve_loop`` over stdio-shaped streams, default (daemon) shell."""
    _use_app_folder(app_dir, monkeypatch)
    out = io.StringIO()
    serve_loop(iter(_lines(requests)), out, **options)
    return [json.loads(line) for line in out.getvalue().splitlines() if line]


def run_in_memory(requests, app_dir: Path, monkeypatch, **options) -> list[dict]:
    """The embedded serve: the same loop over the in-memory pipe, embedded shell."""
    _use_app_folder(app_dir, monkeypatch)
    lines: list[str] = []
    serve = EmbeddedServe(lines.append, **options)
    serve.start()
    for line in _lines(requests):
        serve.send(line)
    serve.close()
    if serve.wait(WAIT_SECONDS) is None:
        raise AssertionError(f"the embedded serve did not end within {WAIT_SECONDS}s of EOF")
    return [json.loads(line) for line in lines if line]


def _scrub(value: Any, forms: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v, forms) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_scrub(v, forms) for v in value]
    if isinstance(value, str):
        for form in forms:
            value = value.replace(form, "<APP>")
    return value


def _is_shell_log(frame: dict) -> bool:
    if frame.get("event") != "stderr":
        return False
    try:
        logged = json.loads(frame.get("line") or "")
    except ValueError:
        return False
    return isinstance(logged, dict) and logged.get("event") in SHELL_LOG_EVENTS


def normalize(frames: list[dict], app_dir: Path) -> dict:
    """-> {"by_id": {id: [frames]}, "unsolicited": [frames], "ready_keys": sorted keys}."""
    forms = tuple(sorted({str(app_dir), str(app_dir).replace("\\", "/"), app_dir.as_posix()},
                         key=len, reverse=True))
    by_id: dict[str, list[dict]] = {}
    unsolicited: list[dict] = []
    ready_keys: list[str] = []
    for frame in frames:
        if frame.get("event") == "ready":
            ready_keys = sorted(frame)
        if frame.get("event") in LIFECYCLE_EVENTS or _is_shell_log(frame):
            continue
        clean = _scrub(frame, forms)
        rid = frame.get("id")
        (by_id.setdefault(str(rid), []) if rid is not None else unsolicited).append(clean)
    return {"by_id": by_id, "unsolicited": unsolicited, "ready_keys": ready_keys}


def frame_differences(desktop: dict, embedded: dict) -> list[str]:
    """Human-readable differences between two :func:`normalize` results; empty = parity."""
    out = []
    for rid in sorted(set(desktop["by_id"]) | set(embedded["by_id"])):
        a, b = desktop["by_id"].get(rid), embedded["by_id"].get(rid)
        if a != b:
            out.append(f"id {rid}: desktop {json.dumps(a)[:400]} != embedded {json.dumps(b)[:400]}")
    if desktop["unsolicited"] != embedded["unsolicited"]:
        out.append(f"unsolicited frames differ: {desktop['unsolicited']!r} != {embedded['unsolicited']!r}")
    if desktop["ready_keys"] != embedded["ready_keys"]:
        out.append(f"ready frame keys differ: {desktop['ready_keys']} != {embedded['ready_keys']}")
    return out


def assert_transport_parity(tmp_path: Path, monkeypatch, requests, *,
                            seed: Callable[[Path], None] | None = None, **options) -> dict:
    """Run ``requests`` through both transports; raise on any difference. Returns both results."""
    legs = {}
    for name, runner in (("desktop", run_stdio), ("embedded", run_in_memory)):
        app_dir = tmp_path / f"{name}-app"
        _use_app_folder(app_dir, monkeypatch)
        if seed is not None:
            seed(app_dir)
        legs[name] = (runner(requests, app_dir, monkeypatch, **options), app_dir)
    desktop = normalize(*legs["desktop"])
    embedded = normalize(*legs["embedded"])
    problems = frame_differences(desktop, embedded)
    assert not problems, "transport parity broken:\n" + "\n".join(problems)
    return {"desktop": legs["desktop"][0], "embedded": legs["embedded"][0],
            "normalized": desktop}
