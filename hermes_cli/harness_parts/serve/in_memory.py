"""The serve loop's third transport: an in-memory pipe, for a runtime embedded in its host app.

stdio is transport #1 and the loopback socket #2; both feed ``ServeSession``'s
one dispatcher. This is #3, for the phone profile: CPython runs inside the app,
and a host shim moves lines of bytes in both directions — it holds no protocol
logic (architecture §3). The SAME ``serve_loop`` answers here: frames in are the
NDJSON lines a stdio client writes, frames out are the lines a stdio client
reads, byte for byte. What differs is only the shell around the loop
(:class:`~hermes_cli.harness_parts.serve.shell.EmbeddedShell`: no pid registry,
no sidecars, no socket, the wheel's baked build stamp) and the store root,
which is the app's own folder.

Host contract (the Stage 3 C shim is its caller):

0. :func:`delete_namespace` for every account whose agent data the host recorded for removal
   (RT-PHONE-NAMESPACE-DELETE-BEFORE-SERVE): the desktop's ``hermes namespace delete``, run in this
   interpreter while it is in no namespace, answering the CLI's own JSON;
1. :func:`configure_app_folder` once, before anything reads ``HERMES_HOME`` —
   module-level constants resolve it at import. ``namespace=`` names the signed-in account's
   namespace (``<app>/hermes-namespaces/<id>``, resolved as the desktop CLI resolves it); without
   it the Hermes home is the base root ``<app>/hermes``;
2. ``agent_runtime.host_store.binding.bind_host_store(...)`` with the OS secure
   store's callbacks, over a store root that contains the app folder's Hermes home,
   INCLUDING ``protect_history_dir``: :meth:`EmbeddedServe.start` hands it the Hermes
   home before the serve thread exists, and the host puts the OS's file protection
   and a no-cloud-backup mark on it (the chat history is upstream's plain SQLite and
   JSONL; the OS protection is its at-rest encryption). :meth:`EmbeddedServe.start`
   refuses (:class:`~agent_runtime.host_store.binding.HostStoreNotBound` /
   ``OutsideStoreRoot`` / ``HistoryProtectionMissing``) without them: unbound, every
   credential would be a plaintext file, and unprotected, the history could reach a
   cloud backup;
3. :class:`EmbeddedServe` with an ``on_frame`` callback (called on the serve's
   threads, one complete line at a time, without the trailing newline);
4. :meth:`EmbeddedServe.send` per inbound line; :meth:`EmbeddedServe.close` is
   EOF, which ends the loop exactly as a closed stdin does.

:meth:`EmbeddedServe.start` first mounts the wheel's forced tree (``phone_forced/`` beside
``app/``, :mod:`agent_runtime.bundle_profiles.forced_tree`) on ``tools.__path__`` /
``plugins.__path__``, so the switched-off code kept code imports resolves while upstream's
directory scans never see it. It also registers the agent loop's lifecycle placeholders
(``agent_runtime.loop_tool_lifecycles``) before anything can import the loop — the
phone wheel does not ship the terminal and browser tool lifecycles it imports —
and rebinds the upstream functions that would start a process to their phone
stand-ins (``agent_runtime.spawn_stand_ins``; only under the phone's config).
The profile's switches (``bundled-phone.yaml``: no provider SDK, no subprocess
worker, no subprocess sign-in) are the host's config, written like any profile's.
"""

from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
from typing import Any, Callable, Iterator, MutableMapping

from agent_runtime.loop_tool_lifecycles import EARLY, ensure_lifecycle_placeholders

# Before the state registry: its import reaches the turn context (upstream v0.22.4), which imports
# ``agent.lsp.deferred``; the phone wheel ships no language server (the rest wait for ``start``).
ensure_lifecycle_placeholders(EARLY)

import hermes_state_registry  # see below
from hermes_cli.harness_parts.serve.session import serve_loop
from hermes_cli.harness_parts.serve.shell import EmbeddedShell

# ``hermes_state_registry`` is loaded up front, never lazily: upstream
# ``SessionDB.close()`` runs ``from hermes_state_registry import release`` from
# ``__del__`` at interpreter exit, when a daemon thread (auto-title, the token
# writer) can be frozen holding the global import lock. Already in ``sys.modules``,
# that line never takes the lock.

__layer__ = "lanes"

__all__ = [
    "EmbeddedServe",
    "InMemoryPipe",
    "app_folder_environment",
    "configure_app_folder",
    "delete_namespace",
    "protect_history_folder",
    "require_bound_host_store",
]

_EOF = object()


def app_folder_environment(app_dir: Path) -> dict[str, str]:
    """The two variables that put Hermes's home and its fork stores inside ``app_dir``.

    The layout mirrors a desktop install's default (``<hermes root>/agent-runtime``),
    so nothing below the store root knows it is on a phone.
    """

    home = Path(app_dir) / "hermes"
    return {"HERMES_HOME": str(home), "HERMES_AGENT_RUNTIME_ROOT": str(home / "agent-runtime")}


#: The namespace the embedded serve of this process runs in, set by :meth:`EmbeddedServe.start`
#: (empty before it, and for a serve over the base root). The serve starts once and cannot be
#: stopped, so that namespace is held until the process ends: :func:`delete_namespace` refuses it
#: as the CLI refuses its own.
_SERVING_NAMESPACE: list[str] = []


def _app_base_environment(app_dir: Path) -> dict[str, str]:
    """The environment of a process in NO namespace over ``app_dir``: the base root ``<app>/hermes``,
    whose namespaces dir is ``<app>/hermes-namespaces``. The app is its own launcher, so no active
    record is read (``HERMES_LAUNCHER_SPAWNED=1``)."""

    from hermes_cli._namespace_bootstrap import DEPENDENCY_ENV, LAUNCHER_ENV

    base = app_folder_environment(app_dir)["HERMES_HOME"]
    return {"HERMES_HOME": base, DEPENDENCY_ENV: base, LAUNCHER_ENV: "1"}


def app_namespace_environment(app_dir: Path, namespace: str, origin: str | None = None) -> dict[str, str]:
    """The environment that puts this interpreter in ``namespace`` over ``app_dir``, or a typed refusal.

    The desktop CLI's own resolution (``_namespace_bootstrap.resolve_cli`` → ``ensure_manifest`` →
    ``env_updates``), never a second one: the same home, store root, head home and fences. The store
    epoch is guarded as the serve guards it, BEFORE the manifest is written, so a refusal
    (``namespace_epoch_newer``; a phone has no consent path for a raise) writes nothing.
    """

    from agent_runtime.namespace_admin import epoch_admitted
    from hermes_cli._namespace_bootstrap import (
        ENV,
        ORIGIN_ENV,
        NamespaceRefused,
        Reason,
        ensure_manifest,
        env_updates,
        requested_origin,
        resolve_cli,
    )

    env = {**_app_base_environment(app_dir), ENV: namespace, **({ORIGIN_ENV: origin} if origin else {})}
    resolution = resolve_cli([], env)
    if resolution.layout is None:
        raise NamespaceRefused(Reason.RESERVED, f"{namespace!r} names the base root, not a namespace; "
                                                "configure without a namespace for the base root")
    epoch_admitted(resolution.layout, env, write=True)
    ensure_manifest(resolution.layout, requested_origin(env))
    return {**env, **env_updates(resolution, env)}


def configure_app_folder(app_dir: Path,
                         environ: MutableMapping[str, str] = os.environ, *,
                         namespace: str | None = None, origin: str | None = None) -> dict[str, str]:
    """Point this interpreter's Hermes home and store root at ``app_dir``; create both.

    With ``namespace``, inside that namespace of ``app_dir`` (:func:`app_namespace_environment`);
    a ``NamespaceRefused`` reaches the host with ``environ`` untouched — never a fallback to the
    base root.
    """

    values = (app_folder_environment(app_dir) if namespace is None
              else app_namespace_environment(app_dir, namespace, origin))
    for key in ("HERMES_HOME", "HERMES_AGENT_RUNTIME_ROOT"):
        Path(values[key]).mkdir(parents=True, exist_ok=True)
    environ.update(values)
    return values


def delete_namespace(app_dir: Path, ns_id: str) -> dict[str, Any]:
    """Remove namespace ``ns_id`` of ``app_dir``: ``hermes namespace delete``, in this interpreter.

    The phone has no CLI process to spawn, so the host calls this before :meth:`EmbeddedServe.start`
    (the process is then in no namespace). Returns the verb's dict, or the refusal's payload — the
    same JSON the CLI prints: ``namespace_not_found``, ``namespace_reserved`` (``base``),
    ``namespace_invalid_id``, ``namespace_busy``, and ``namespace_in_use_by_this_process`` for the
    namespace this process's embedded serve runs in. ``os.environ`` is never read or written.
    """

    from agent_runtime import namespace_admin
    from hermes_cli._namespace_bootstrap import ENV, NamespaceRefused

    env = _app_base_environment(app_dir)
    # MUTATION: drop this line and test_phone_namespace_delete_before_serve's "the served namespace is
    # refused after start" reddens (the delete empties the namespace the serve runs in).
    env.update({ENV: _SERVING_NAMESPACE[0]} if _SERVING_NAMESPACE else {})
    try:
        return namespace_admin.delete(ns_id, env)
    except NamespaceRefused as exc:
        return exc.payload()


class InMemoryPipe:
    """Host -> runtime lines: the iterable ``serve_loop`` reads, fed from any thread."""

    def __init__(self) -> None:
        self._queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._closed = threading.Event()

    def write_line(self, line: str) -> None:
        if self._closed.is_set():
            raise ValueError("the in-memory pipe is closed")
        self._queue.put(line if line.endswith("\n") else line + "\n")

    def close(self) -> None:
        """EOF. Idempotent."""

        if not self._closed.is_set():
            self._closed.set()
            self._queue.put(_EOF)

    def __iter__(self) -> Iterator[str]:
        while True:
            item = self._queue.get()
            if item is _EOF:
                return
            yield item


class _LineSink:
    """Runtime -> host: the writer ``serve_loop`` emits to, split into complete lines."""

    def __init__(self, on_frame: Callable[[str], None]) -> None:
        self._on_frame = on_frame
        self._pending = ""
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        with self._lock:
            self._pending += text
            *lines, self._pending = self._pending.split("\n")
            for line in lines:
                self._on_frame(line)
        return len(text)

    def flush(self) -> None:
        return None


def require_bound_host_store(home: Path | None = None) -> None:
    """Refuse an embedded serve whose host has not bound a secure store over its Hermes home.

    Raises ``HostStoreNotBound`` when nothing is bound, ``OutsideStoreRoot`` when the
    binding's root does not contain the Hermes home (its secret files would have no slot).
    ``home`` defaults to the RESOLVED root (``get_hermes_home``) — the one the serve will
    actually write under — never a second read of the environment.
    """

    from agent_runtime.host_store.binding import OutsideStoreRoot, require
    from hermes_constants import get_hermes_home

    bound = require()
    home = Path(os.path.abspath(home if home is not None else get_hermes_home()))
    if not home.is_relative_to(bound.store_root):
        raise OutsideStoreRoot(f"Hermes home {home} is not under the host store root {bound.store_root}")


def protect_history_folder(home: Path | None = None) -> Path:
    """Have the host protect the Hermes home that holds the chat history; return it.

    The phone boot's one call to the host contract's ``protect_history_dir`` (see
    :mod:`agent_runtime.host_store.binding`). ``home`` defaults to the resolved root,
    as in :func:`require_bound_host_store`. Raises ``HistoryProtectionMissing`` when the
    host bound no such callback, and whatever the host raises when it cannot protect.
    """

    from agent_runtime.host_store.binding import require
    from hermes_constants import get_hermes_home

    home = Path(os.path.abspath(home if home is not None else get_hermes_home()))
    home.mkdir(parents=True, exist_ok=True)
    return require().protect_history_dir(home)


class EmbeddedServe:
    """One embedded runtime: ``serve_loop`` on its own thread over an :class:`InMemoryPipe`.

    ``options`` are ``ServeSession``'s keyword arguments; the embedded shell
    refuses the daemon levers (socket, service, end-reason sidecar, parent pid).
    """

    def __init__(self, on_frame: Callable[[str], None], **options: Any) -> None:
        self._pipe = InMemoryPipe()
        self._sink = _LineSink(on_frame)
        self._options = {"shell": EmbeddedShell(), **options}
        self._thread: threading.Thread | None = None
        self._exit_code: int | None = None
        self._error: BaseException | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("an embedded serve starts once per app process")
        from agent_runtime.bundle_profiles.forced_tree import mount_forced_tree

        mount_forced_tree()  # the wheel's forced set resolves by import; the directory scans never see it
        require_bound_host_store()
        protect_history_folder()  # before anything writes history: the OS protection + no cloud backup
        from agent_runtime.loop_tool_lifecycles import ensure_lifecycle_placeholders

        ensure_lifecycle_placeholders()  # before any request can import the agent loop
        from agent_runtime.provider_sdk_shim import ensure_provider_sdk_shim

        ensure_provider_sdk_shim()  # the phone's `openai`: upstream's SDK import sites get the SDK-free client
        from agent_runtime.psutil_stand_in import ensure_psutil_stand_in

        ensure_psutil_stand_in()  # the phone's `psutil`: upstream's process reads see an empty table
        from agent_runtime.spawn_stand_ins import ensure_spawn_stand_ins

        ensure_spawn_stand_ins()  # upstream functions that start a process answer as a phone must
        from agent_runtime.phone_native_libs import load_phone_native_libs

        load_phone_native_libs()  # Android: Pillow's image libraries, by path, before anything imports PIL
        from agent_runtime.phone_tls_trust import ensure_phone_tls_trust

        ensure_phone_tls_trust()  # Android/iOS: certifi's anchors, before any HTTPS client is built
        from hermes_cli._namespace_bootstrap import namespace_stamp

        _SERVING_NAMESPACE[:] = [namespace_stamp()] if namespace_stamp() else []
        self._thread = threading.Thread(target=self._run, name="hermes-embedded-serve", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            from agent_runtime.bundle_profiles.phone_hint import install_phone_platform_hint

            install_phone_platform_hint()  # the phone agent is told its limits (upstream's PLATFORM_HINTS)
            self._exit_code = serve_loop(self._pipe, self._sink, **self._options)
        except BaseException as exc:  # reported through wait(); the host decides
            self._error = exc

    def send(self, line: str) -> None:
        self._pipe.write_line(line)

    def close(self) -> None:
        self._pipe.close()

    def wait(self, timeout: float | None = None) -> int | None:
        """The loop's exit code once it ended; None while it still runs. Re-raises its failure."""

        if self._thread is None:
            raise RuntimeError("the embedded serve was never started")
        self._thread.join(timeout)
        if self._thread.is_alive():
            return None
        if self._error is not None:
            raise self._error
        return self._exit_code
