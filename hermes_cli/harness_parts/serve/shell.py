"""The serve's PROCESS shell, apart from its dispatch: which host concerns a serve owns.

``ServeSession`` is two things. The dispatcher — frames in, ``runtime.*`` and
argv answers out, the pool, drain and subscriptions — is the same wherever
Hermes runs. The daemon shell around it is not: a desktop serve is its own OS
process, so it registers a pid row other clients discover it by (liveness read
through ``psutil``), keeps an end-reason sidecar and a stderr log beside that
row, stamps its build from the git checkout it was started from, and mints the
socket lane's token. An embedded runtime (the phone profile: CPython inside the
app, frames over an in-memory pipe) has none of those — no pid of its own, no
other client, no checkout, no socket.

The shell is injected, like every other process lever of ``ServeSession``
(``socket_lane``, ``service``, ``record_end_reason``, ``parent_pid``):

* :func:`default_shell` — the desktop's :class:`~hermes_cli.harness_parts.serve.
  daemon_shell.DaemonShell`, imported lazily so the embedded profile's import
  closure never contains it. Every existing caller gets it; behaviour unchanged.
* :class:`EmbeddedShell` — no registry, no sidecars, no token file, the wheel's
  baked build stamp. It refuses the daemon-only levers outright, so an embedded
  serve cannot be half-configured into one that expects a process.

The shell answers with the SAME frame blocks the ready frame always carried;
what an embedded shell cannot have is a typed ``not_applicable:embedded`` rather
than an absent key, because an absent key reads as "old runtime".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

__layer__ = "lanes"

__all__ = [
    "EMBEDDED_NOT_APPLICABLE",
    "EmbeddedShell",
    "ServeShell",
    "default_shell",
]

#: The typed word an embedded shell reports where a daemon reports a pid-row fact.
EMBEDDED_NOT_APPLICABLE = "not_applicable:embedded"


class ServeShell(Protocol):
    """What ``ServeSession`` asks of the host process it runs in."""

    #: ``"daemon"`` or ``"embedded"``; rides the ready frame's ``shell`` key.
    kind: str

    def refuse_levers(self, *, socket_lane: bool, service: bool, record_end_reason: bool,
                      parent_pid: int | None) -> None:
        """Raise ``ValueError`` for a process lever this shell cannot honour."""

    def build_block(self) -> dict[str, Any]:
        """The ready frame's ``build`` block."""

    def version_build(self) -> dict[str, Any]:
        """The ``version`` reply's full ``build`` stamp (provenance and process facts)."""

    def auth_block(self, store_root: Path) -> dict[str, Any]:
        """The ready frame's ``auth`` block (socket token posture)."""

    def register_instance(self, store_root: Path, **row: Any) -> dict[str, Any]:
        """Advertise this runtime; the ready frame's ``instance`` block."""

    def unregister_instance(self, store_root: Path) -> tuple[bool, Path | None]:
        """Withdraw the advertisement -> (removed, the row's path or None)."""

    def open_stderr_log(self, store_root: Path, *, boot_id: str, build: dict[str, Any]) -> Any:
        """The service runtime's own stderr file, or None."""

    def prune_stale_instances(self, store_root: Path, *, emit: Callable[[dict[str, Any]], None],
                              boot_id: str) -> dict[str, Any]:
        """Drop provably dead rows; the prune report."""

    def prune_ended(self, store_root: Path) -> None:
        """Retention floor for end-reason sidecars."""


class EmbeddedShell:
    """The shell of a runtime that lives inside its host app (the phone profile).

    Nothing here touches a process table, a subprocess or a registry directory:
    the app IS the only client, so there is nothing to discover and nothing to
    reap, and the build is the wheel's baked stamp.
    """

    kind = "embedded"

    def refuse_levers(self, *, socket_lane: bool, service: bool, record_end_reason: bool,
                      parent_pid: int | None) -> None:
        asked = [name for name, on in (("socket_lane", socket_lane), ("service", service),
                                       ("record_end_reason", record_end_reason),
                                       ("parent_pid", parent_pid is not None)) if on]
        if asked:
            raise ValueError(f"an embedded serve has no process to own: {', '.join(asked)} refused")

    def build_block(self) -> dict[str, Any]:
        from agent_runtime.build_stamp import baked_build_stamp

        return baked_build_stamp().frame_payload()

    def version_build(self) -> dict[str, Any]:
        from agent_runtime.build_stamp import baked_build_stamp

        return baked_build_stamp().payload()

    def auth_block(self, store_root: Path) -> dict[str, Any]:
        return {"token_file": EMBEDDED_NOT_APPLICABLE}

    def register_instance(self, store_root: Path, **row: Any) -> dict[str, Any]:
        return {"outcome": EMBEDDED_NOT_APPLICABLE}

    def unregister_instance(self, store_root: Path) -> tuple[bool, Path | None]:
        return True, None

    def open_stderr_log(self, store_root: Path, *, boot_id: str, build: dict[str, Any]) -> Any:
        return None

    def prune_stale_instances(self, store_root: Path, *, emit: Callable[[dict[str, Any]], None],
                              boot_id: str) -> dict[str, Any]:
        return {}

    def prune_ended(self, store_root: Path) -> None:
        return None


def default_shell() -> ServeShell:
    """The desktop daemon shell — every caller that names none gets today's serve."""

    from hermes_cli.harness_parts.serve.daemon_shell import DaemonShell

    return DaemonShell()
