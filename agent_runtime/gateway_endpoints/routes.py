"""The routing table's owner of ``0.0.0.0/0`` (R-D8), per platform.

One bounded ``route`` / ``ip`` / ``ifconfig`` spawn per question, the three
platform parsers, and ``default_route_address`` which picks between them.
``None`` on any doubt; the caller then ranks by the R-D2 probe alone.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final

from .addresses import _WILDCARD_HOSTS, _ipv4

__layer__ = "stores"

#: Where the default-route probe *points*. A PUBLIC unicast address, and that is
#: the whole of R-D2's first half: the probe asks the kernel "which of my
#: addresses would carry traffic to the INTERNET", and the answer is only that
#: question if the far address is on the internet. This used to be
#: ``10.255.255.255``, which asks "which address reaches 10/8" — and on a machine
#: with a private 10.x adapter beside the Wi-Fi (a VM host bridge, a corporate
#: virtual NIC) the kernel correctly answers with the 10.x address, so the
#: router-granted LAN address was ranked below an interface with no gateway at
#: all. Measured on the operator's Windows PC 2026-09-04: the LAN address
#: 192.168.1.203 came out THIRD.
#:
#: ``1.1.1.1:53`` resolves nothing and is never contacted — see the connect
#: comment below — so this is a routing-table lookup wearing a socket, not a
#: dependency on that resolver being up or on this machine having a route at all.
_DEFAULT_ROUTE_PROBE = ("1.1.1.1", 53)

#: How long ONE routing-table command (R-D8) may take before it is abandoned.
#: The read runs inside ``gateway id``, which the launcher's sheet calls on a
#: timer, so the failure worth defending against is not a wrong answer — the
#: R-D2 probe still ranks behind it — but a wedged ``route.exe`` holding the
#: sheet. Two seconds is far above the ~30 ms these commands actually cost.
_ROUTE_COMMAND_TIMEOUT_SECONDS = 2.0


def run_route_command(argv: list[str]) -> str | None:
    """One routing-table command's stdout, or ``None``. Never raises.

    Every way this can fail — the binary missing, a non-zero exit, a hang, a
    localised console codepage, a sandbox that forbids spawning at all — means
    the same thing to the caller: *the table did not answer, fall back to the
    R-D2 probe.* So they collapse to one ``None`` rather than a taxonomy nobody
    would branch on. ``check=False`` and the bare ``except`` are the point of
    this function, not a shortcut taken inside it.
    """

    import subprocess
    import sys

    extra: dict[str, Any] = {}
    if sys.platform == "win32":
        # ``route.exe`` is a console program and this CLI is routinely spawned
        # by a windowless launcher process; without this the operator would see
        # a console blink every time the sheet refreshes.
        flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if flag:
            extra["creationflags"] = flag
    try:
        completed = subprocess.run(
            argv,
            # This CLI is spoken to over stdio by a launcher (see
            # ``CALLER_STDIO_OWNER``), so a child that inherited stdin could eat
            # a frame addressed to us. ``route``/``ip``/``ifconfig`` read none.
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_ROUTE_COMMAND_TIMEOUT_SECONDS,
            check=False,
            **extra,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout or ""


def windows_default_route_address(text: str) -> str | None:
    """The ``Interface`` column of ``route print -4``'s true default row.

    The row shape is the anchor, not the ``Active Routes:`` header, which is
    localised on a non-English Windows. Five whitespace-separated fields, the
    first two exactly ``0.0.0.0``, the fourth a v4 address, the fifth an
    integer — which is precisely the Active Routes shape and precisely not the
    Persistent Routes one (four fields, metric ``Default``).

    **The netmask test is the whole of R-D8.** A full-tunnel VPN client like
    PIA installs ``0.0.0.0/1`` + ``128.0.0.0/1``, which cover every address and
    beat ``0.0.0.0/0`` on specificity, so the datagram probe answers with the
    tunnel on a machine whose LAN address is the one a peer can reach. Those
    rows carry netmask ``128.0.0.0`` and are rejected here by string equality;
    only an owner of ``0.0.0.0/0`` is the router-granted address.

    Several default rows (two NICs on one LAN) are decided by the lowest Metric,
    which is the kernel's own tie-break. Any doubt at all — a row that will not
    parse — drops that row rather than guessing at it.
    """

    best: tuple[int, str] | None = None
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 5:
            continue
        destination, netmask, _gateway, interface, metric = fields
        if destination != "0.0.0.0" or netmask != "0.0.0.0":
            continue
        if _ipv4(interface) is None or interface in _WILDCARD_HOSTS:
            continue
        try:
            cost = int(metric)
        except ValueError:
            continue
        if best is None or cost < best[0]:
            best = (cost, interface)
    return None if best is None else best[1]


def macos_default_route_interface(text: str) -> str | None:
    """The ``interface:`` line of ``route -n get default`` — a NAME, not an
    address, which is why macOS needs the second command below."""

    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "interface":
            return value.strip() or None
    return None


def first_inet_address(text: str) -> str | None:
    """The first ``inet <address>`` of an ``ifconfig``/``ip addr`` block.

    One reader for both platforms: macOS writes ``inet 192.168.1.5 netmask
    0xffffff00`` and Linux writes ``inet 192.168.1.42/24 brd …``, and the only
    difference that matters is the prefix length, stripped here. ``inet6`` does
    not match the token. A first row that will not parse as v4 answers ``None``
    rather than skipping to a later one — R-D8's rule is "any parse doubt →
    ``None``", and a second address on that interface is a different address
    than the one the table named.
    """

    for line in text.splitlines():
        fields = line.split()
        for index, field in enumerate(fields[:-1]):
            if field != "inet":
                continue
            candidate = fields[index + 1].split("/", 1)[0]
            return candidate if _ipv4(candidate) else None
    return None


def linux_default_route(text: str) -> tuple[str | None, str | None]:
    """``(src, dev)`` from the first ``default`` line of ``ip -4 route show
    default``.

    ``src`` is the address the kernel will put on packets leaving by that route
    and is therefore the answer outright when present; ``dev`` is the fallback
    the caller turns into an address with a second command. ``ip`` prints
    default routes in metric order, so the first line is the lowest-cost one —
    the same tie-break the Windows reader does arithmetic for.
    """

    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] != "default":
            continue
        source: str | None = None
        device: str | None = None
        for index, field in enumerate(fields[:-1]):
            if field == "src" and source is None:
                source = fields[index + 1]
            elif field == "dev" and device is None:
                device = fields[index + 1]
        if source is not None and _ipv4(source) is None:
            source = None
        return source, device
    return None, None


def default_route_address() -> str | None:
    """R-D8: the address that owns ``0.0.0.0/0``, read from the routing table.

    The operator's sentence — *"the exact router-granted address"* — made
    mechanical, and the correction D1's field notes earned: the datagram probe
    of R-D2 asks "which of my addresses reaches the internet", and with a
    full-tunnel VPN up the honest answer is the tunnel's. The routing TABLE can
    still be asked the different question "who owns the default route", and on
    the machine that motivated this it answers Wi-Fi while every probe
    destination answers PIA.

    Stdlib subprocess, one command per platform (two on macOS and on a Linux
    route without ``src``), each bounded by
    :data:`_ROUTE_COMMAND_TIMEOUT_SECONDS`. ``None`` on any doubt whatsoever,
    which the caller reads as "rank by R-D2 alone" — this ruling only ever
    promotes an address ahead of the probe's, it never removes one, so a
    silent failure here costs the pre-D1b ordering and nothing more.
    """

    import sys

    return ROUTE_PROBES.get(sys.platform, _linux_probe)()


def _windows_probe() -> str | None:
    printed = run_route_command(["route", "print", "-4"])
    return windows_default_route_address(printed) if printed else None


def _macos_probe() -> str | None:
    printed = run_route_command(["route", "-n", "get", "default"])
    interface = macos_default_route_interface(printed) if printed else None
    if not interface:
        return None
    printed = run_route_command(["ifconfig", interface])
    return first_inet_address(printed) if printed else None


def _linux_probe() -> str | None:
    printed = run_route_command(["ip", "-4", "route", "show", "default"])
    if not printed:
        return None
    source, device = linux_default_route(printed)
    if source:
        return source
    if not device:
        return None
    printed = run_route_command(["ip", "-4", "-o", "addr", "show", "dev", device])
    return first_inet_address(printed) if printed else None


#: ``sys.platform`` -> the probe that asks THAT platform's routing table. Every
#: platform outside the table asks ``ip`` (the Linux probe), which is what the
#: ladder this replaced did in its final arm.
ROUTE_PROBES: Final[Mapping[str, Callable[[], str | None]]] = MappingProxyType(
    {
        "win32": _windows_probe,
        "darwin": _macos_probe,
        "linux": _linux_probe,
    }
)
