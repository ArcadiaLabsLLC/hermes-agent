"""A TCP connect to a closed loopback port is refused at once instead of after Windows' SYN retries.

Windows answers a loopback connect to a port nothing listens on only after its SYN retries,
2.3-2.5 s each (measured 2026-10-17, ``Harness_Brain/20 — Active Initiatives/r-perf-2026-10-17.md``);
about 70 test files name ``127.0.0.1:1`` as a dead endpoint. Linux and macOS refuse at once.

"Nothing listens" is decided per connect by a local probe, never a port list: an exclusive bind of
the port on BOTH wildcard addresses (``0.0.0.0`` and dual-stack ``::``). Any socket bound to that
port on any address — a listener on loopback, a wildcard, ``::1``, or even a client's local port —
makes the bind fail, and the connect goes to the real ``connect`` unchanged. The probe can only
over-approximate "something is there", which costs the old wait and never a wrong refusal. The
answer given is the one the kernel gives eventually: ``ConnectionRefusedError(ECONNREFUSED)`` from
``connect``, ``ECONNREFUSED`` from ``connect_ex``.

Covers every Python-level ``socket.socket`` connect (``create_connection``, ``http.client``,
urllib, urllib3/requests, httpx sync, the selector event loop). Not covered: the proactor event
loop's ``ConnectEx`` and child processes. A test that patches ``socket.socket.connect`` itself
replaces this wrapper for its own body.
"""

from __future__ import annotations

import errno
import socket

_LOOPBACK_NAMES = frozenset({"localhost", "localhost.", "::1", "0:0:0:0:0:0:0:1"})


def _host_is_loopback(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    name = host.split("%", 1)[0].lower()
    return name in _LOOPBACK_NAMES or name.startswith("127.")


def _target_port(sock: socket.socket, address: object) -> int | None:
    """The port of a TCP connect to a loopback address, else None (leave the connect alone)."""

    if sock.family not in (socket.AF_INET, socket.AF_INET6) or sock.type != socket.SOCK_STREAM:
        return None
    if not isinstance(address, tuple) or len(address) < 2 or not _host_is_loopback(address[0]):
        return None
    port = address[1]
    return port if isinstance(port, int) and 0 < port < 65536 else None


def port_is_unbound(port: int) -> bool:
    """True when no socket on this host holds ``port`` on any address, by exclusive wildcard binds."""

    for family, host in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
        try:
            probe = socket.socket(family, socket.SOCK_STREAM)
        except OSError:
            continue  # the family is unavailable here: nothing can listen on it
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            if family == socket.AF_INET6:
                probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            _REAL_BIND(probe, (host, port))
        except OSError:
            return False
        finally:
            probe.close()
    return True


_REAL_BIND = socket.socket.bind


def _refused(port: int) -> ConnectionRefusedError:
    return ConnectionRefusedError(
        errno.ECONNREFUSED, f"connection refused: nothing listens on loopback port {port} (tests/_downstream/closed_loopback.py)"
    )


def install() -> None:
    """Wrap ``socket.socket.connect`` and ``connect_ex`` once per process (idempotent)."""

    real_connect = socket.socket.connect
    if getattr(real_connect, "_fork_closed_loopback", False):
        return
    real_connect_ex = socket.socket.connect_ex

    def connect(self, address):
        port = _target_port(self, address)
        if port is not None and port_is_unbound(port):
            raise _refused(port)
        return real_connect(self, address)

    def connect_ex(self, address):
        port = _target_port(self, address)
        if port is not None and port_is_unbound(port):
            return errno.ECONNREFUSED
        return real_connect_ex(self, address)

    for wrapper, real in ((connect, real_connect), (connect_ex, real_connect_ex)):
        wrapper._fork_closed_loopback = True  # type: ignore[attr-defined]
        wrapper.__wrapped__ = real  # type: ignore[attr-defined]
    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
