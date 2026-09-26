"""Where should the OTHER side dial this install — and was a failed dial ours?

The listener's endpoint (live sidecar, then config, then unknown), this
machine's addresses in dial order, the candidate list a peer row and a
payload carry, the one dial host, and R-D20's on-link classification of a
failed dial (it needs the same enumeration).
"""

from __future__ import annotations

from typing import Any

from .addresses import (
    DIAL_LOCAL_POLICY,
    DIAL_UNREACHABLE,
    MAX_CANDIDATE_ENDPOINTS,
    _HOST_UNREACHABLE_ERRNOS,
    _UNOFFERABLE_PREFIXES,
    _V6_LINK_LOCAL,
    _V6_UNIQUE_LOCAL,
    _WILDCARD_HOSTS,
    _WSAEHOSTUNREACH,
    _address_rank,
    _in_network,
    _ipv4,
    _shares_24,
    _shares_64,
)
from .routes import _DEFAULT_ROUTE_PROBE, default_route_address

__layer__ = "stores"

#: The three answers :func:`listener_endpoint` gives about WHERE its endpoint
#: came from, read by name at every compare site. Plain constants and not an
#: Enum: ``unknown`` is a fork-wide word (``turn_visibility.VisibilityState``),
#: and this vocabulary is this module's (layout sheet gateway_commands.md §2).
SOURCE_LIVE = "live"
SOURCE_CONFIG = "config"
SOURCE_UNKNOWN = "unknown"


def gateway_listen_config() -> tuple[str | None, int]:
    """``(host, port)`` from ``remote_gateway.*``; ``(None, …)`` means off.

    The FIRST reader of the keys Stage 0a declared — and the read that found
    they had never existed: Stage 0a put them under ``"gateway"``, which is
    already a top-level key in ``config_defaults``' one big dict literal, so
    Python kept the later entry and dropped this one at parse time. They are
    ``remote_gateway.*`` now, guarded by an AST test.

    ``listen`` is a HOST STRING when it is on, and a boolean ``True`` is
    deliberately refused rather than resolved to a default interface: an
    operator opening a port onto a LAN should have to say which one, and
    "guessed an interface for you" is not a sentence this runtime should be able
    to say about a listener that executes agents with tools. Anything unreadable
    is off, because the failure direction for a config that cannot be parsed is
    "do not bind".
    """

    try:
        from hermes_cli.config import load_config_readonly

        block = load_config_readonly().get("remote_gateway") or {}
    except Exception:
        return None, 0
    if not isinstance(block, dict):
        return None, 0
    listen = block.get("listen")
    if not isinstance(listen, str):
        return None, 0
    host = listen.strip()
    if not host or host.lower() in {"false", "off", "no", "true"}:
        return None, 0
    try:
        port = int(block.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    return host, max(0, min(65535, port))


def listener_endpoint(store_root) -> dict[str, Any]:
    """Where a phone should dial, and HOW CONFIDENT this answer is.

    Three sources, and the block says which one answered, because they are not
    equally good and an operator reading a port needs to know whether it is the
    one a listener is actually on:

    * ``live`` — the running serve's ownership sidecar. Authoritative, and the
      only source that can name an EPHEMERAL port, which exists nowhere else.
    * ``config`` — ``remote_gateway.*``. What the next boot will use. Correct
      whenever the port is pinned, and silent about whether anything is
      listening.
    * ``unknown`` — the lane is off, or configured and not yet started.

    Deliberately not an error. Pairing before the first boot is a legitimate
    thing to do (``gateway rename`` already supports it), and refusing to mint a
    code because a serve is not up would make the ceremony depend on an ordering
    nobody chose.
    """

    from agent_runtime.serve_socket.owner_lock import read_socket_owner

    try:
        owner = read_socket_owner(store_root) or {}
    except Exception:
        owner = {}
    live = owner.get("gateway") if isinstance(owner, dict) else None
    if isinstance(live, dict) and live.get("port"):
        return {
            "host": live.get("host"),
            "port": int(live["port"]),
            "source": SOURCE_LIVE,
        }
    host, port = gateway_listen_config()
    if host is None:
        return {"host": None, "port": None, "source": SOURCE_UNKNOWN}
    return {"host": host, "port": port or None, "source": SOURCE_CONFIG}


def machine_addresses() -> list[str]:
    """This machine's dialable addresses, best-effort, stdlib only, IN DIAL ORDER.

    Called ONLY when the listener bound a wildcard — the case where the config
    says "every interface" and therefore names none. Three sources, deduped:

    0. **The routing table's owner of ``0.0.0.0/0``**
       (:func:`default_route_address`, R-D8), which is the only source that
       tells a LAN apart from a full-tunnel VPN. Silent when the table declines,
       and then the two below are exactly what D1 shipped.
    1. **The default-route probe**, using the UDP-connect trick: a
       ``SOCK_DGRAM`` socket is *connected* to :data:`_DEFAULT_ROUTE_PROBE` and
       asked what local address the kernel would use. **No packet is sent** —
       connect on a datagram socket only fixes the peer — so this costs no
       traffic, needs no reachability, and answers with the cable unplugged.
    2. **The hostname's records**, v4 then v6, which is what the machine calls
       itself and is usually right on a LAN with mDNS or a DHCP-registering DNS.

    What S4's first hardware attempt changed is that DISCOVERY ORDER is no
    longer OFFER ORDER. The two sources answer "which addresses exist" in
    whatever order the resolver feels like, and the list is then capped at
    :data:`MAX_CANDIDATE_ENDPOINTS` — so on a machine with several adapters the
    router-granted address could be truncated away entirely by addresses nobody
    can reach. :func:`_address_rank` decides the order, the cap is applied
    AFTER it, and the first row is therefore the one R-D4's sheet prints.

    Every source is wrapped: name resolution on a laptop that has just changed
    networks raises in ways not worth a taxonomy, and this function's honest
    failure is an empty list — the same answer as "no address to offer", which
    the ack already knows how to say.
    """

    import socket

    found: list[str] = []

    def _keep(value) -> str | None:
        # Zone index off FIRST (``fe80::1%eth0``): a scoped address is
        # meaningless to the machine we would hand it to, and the prefix test
        # below has to see the address rather than the interface name.
        host = str(value or "").strip().lower().split("%", 1)[0]
        if not host or host in _WILDCARD_HOSTS or host == "::1":
            return None
        if host.startswith(_UNOFFERABLE_PREFIXES):
            return None
        if host not in found:
            found.append(host)
        return host

    # R-D8 first, because it is the authority the probe only approximates: it
    # is kept like any other discovered address (deduped, and dropped if it is
    # loopback or link-local), and it takes rank 0 from :func:`_address_rank`.
    # A machine whose hostname resolves to nothing and whose probe names the
    # tunnel therefore still offers its LAN address, because this source found
    # it rather than merely reordering what the other two found.
    table_route = _keep(default_route_address())

    default_route: str | None = None
    probe = None
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(_DEFAULT_ROUTE_PROBE)
        default_route = _keep(probe.getsockname()[0])
    except Exception:
        pass
    finally:
        if probe is not None:
            try:
                probe.close()
            except Exception:
                pass

    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, family):
                _keep(info[4][0])
        except Exception:
            continue

    # Stable, so two addresses of the same rank keep the order they were
    # discovered in — the sort decides between KINDS of address and never
    # reorders within one, which is what makes a two-adapter machine's answer
    # reproducible run to run.
    ordered = sorted(
        found, key=lambda host: _address_rank(host, default_route, table_route)
    )
    return ordered[:MAX_CANDIDATE_ENDPOINTS]


def _is_on_link(host: str, addresses: list[str] | None = None) -> bool:
    """Is ``host`` on a segment one of THIS machine's own addresses sits on?

    The question R-D20 turns on, because it is what separates "the kernel has no
    idea where that is" from "the kernel knows exactly where that is and will not
    send". The Mac's ARP table had ``192.168.1.203`` resolved while every packet
    to it came back ``EHOSTUNREACH`` — the address was on-link and the refusal
    was a policy.

    v4 asks :func:`_shares_24` against :func:`machine_addresses`, the same
    prefix test D1's ranking already uses. v6 answers from the address itself
    wherever it can: link-local is on-link by definition, unique-local shares a
    /64 with one of ours or it does not, and a global v6 address is never called
    on-link — see :data:`_V6_LINK_LOCAL`.
    """

    host = str(host or "").strip().lower().split("%", 1)[0]
    if not host:
        return False
    if ":" in host:
        if _in_network(host, _V6_LINK_LOCAL):
            return True
        if not _in_network(host, _V6_UNIQUE_LOCAL):
            return False
        mine = machine_addresses() if addresses is None else list(addresses)
        return any(_shares_64(host, address) for address in mine)
    if _ipv4(host) is None:
        return False
    mine = machine_addresses() if addresses is None else list(addresses)
    return any(_shares_24(host, address) for address in mine)


def classify_dial_error(exc, host: str, *, addresses: list[str] | None = None) -> str:
    """R-D20: which of :data:`DIAL_LOCAL_POLICY` / :data:`DIAL_UNREACHABLE` this is.

    ``EHOSTUNREACH`` reads as a statement about the NETWORK and on macOS 15 it is
    a statement about this process's PERMISSIONS. Measured on the operator's Mac
    2026-09-04: Local Network privacy had never been granted to the responsible
    app, so the kernel answered errno 65 for every host on the Mac's own /24
    except the router — on every port and on ICMP, with the ARP entry resolved,
    in 177 ms because nothing was ever sent. hermes called that ``OSError`` →
    ``runtime_unavailable``, the launcher painted ``Unreachable``, and the
    operator was sent to the router for a permission on their own machine.

    So the same errno against an ON-LINK address is a different word from the
    same errno against an address somewhere out on the internet, and only the
    on-link one is ``local_policy``. A non-on-link ``EHOSTUNREACH`` is a plain
    dial failure and keeps every word it had.

    ``addresses`` exists for the caller that already knows this machine's
    addresses and for tests; when it is ``None`` this asks
    :func:`machine_addresses` — but only AFTER the errno test, so the common
    refusals (``ConnectionRefusedError``, a timeout) never pay for a
    routing-table read.
    """

    if not isinstance(exc, OSError):
        return DIAL_UNREACHABLE
    number = getattr(exc, "errno", None)
    winerror = getattr(exc, "winerror", None)
    if number not in _HOST_UNREACHABLE_ERRNOS and winerror != _WSAEHOSTUNREACH:
        return DIAL_UNREACHABLE
    return DIAL_LOCAL_POLICY if _is_on_link(host, addresses) else DIAL_UNREACHABLE


def candidate_endpoints(store_root) -> list[dict]:
    """Where the OTHER install should dial this one, as a peer row's list.

    Built from :func:`listener_endpoint` — the same three sources, the same confidence
    ordering — and reduced to the shape ``gateway_peers.clean_endpoints`` keeps.
    Empty when this root has no address to offer, which is a real state and not
    an error: an install that has never opened its gateway listener can still
    JOIN another install and talk to it. The edge simply works in one direction
    until it listens, and the ack says so rather than leaving the operator to
    find out when a call from the far side never arrives.

    **The wildcard case is where S2 changed the answer, and it is a widening
    rather than a fix to something wrong.** ``0.0.0.0`` used to return ``[]``
    with a correct argument attached — a bind is not an address, and writing one
    into a peer row produces a dial that always fails and looks like the peer
    being down. What was missing was the other half: an operator who binds a
    wildcard has not declined to be reachable, they have declined to CHOOSE, and
    this machine can answer that question itself. So a wildcard now enumerates
    :func:`machine_addresses`; a concrete host is still exactly one row;
    ``unknown`` is still ``[]``.

    Computed in the CLI process, at CLI time, and deliberately NOT put on the
    greeting frame: interface enumeration is a question whose answer changes
    when somebody joins a wifi network, and a frame minted at boot would carry a
    stale one for the life of the serve.
    """

    endpoint = listener_endpoint(store_root)
    host, port = endpoint.get("host"), endpoint.get("port")
    if not host or not port:
        return []
    port = int(port)
    if str(host).strip().lower() in _WILDCARD_HOSTS:
        return [{"host": address, "port": port} for address in machine_addresses()]
    # A listener pinned to loopback is kept as a row rather than filtered: the
    # two-roots lane is exactly that shape — two installs on one box, pairing
    # over 127.0.0.1 on purpose. The filter above exists for ENUMERATED
    # addresses, where a loopback row would be noise beside a real one.
    return [{"host": str(host), "port": port}]


def dial_host(endpoints: list[dict]) -> tuple[str, int] | None:
    """The ONE address every payload writer names, or ``None``.

    R-D1: *a payload host is a dialable address or the verb refuses.* Before
    this existed, four writers each took ``listener_endpoint(root)["host"]`` — the
    LISTENER'S BIND — and a wildcard bind therefore put the literal ``0.0.0.0``
    into a join payload, a QR payload and a grant. That is not an address: on
    Windows dialling it fails with ``WSAEADDRNOTAVAIL`` and on macOS it resolves
    to the dialler's own loopback, so both machines in S4's hardware attempt
    reported the far install as unreachable when nothing was wrong with either
    listener.

    The answer is simply the first of :func:`candidate_endpoints`, which after
    R-D2 is the default-route address. Defined as its own function rather than
    inlined four times because "which address do we hand out" must have exactly
    one answer — the same reason :func:`candidate_endpoints` exists — and because
    ``gateway id`` prints it as ``dial_host`` for the launcher's sheet to read
    (R-D4). ``None`` when the list is empty, which the callers distinguish from
    "the lane is off" using the endpoint's own ``source``.

    **It takes the LIST, not the root, and D1b is why.** D1 wrote it as
    ``dial_host(store_root)``, which enumerated a second time; enumerating was
    two socket calls then and is a routing-table process spawn now (~0.4 s on
    the operator's Windows PC), and both callers — ``_dial_target`` and
    ``gateway id`` — were already holding the list they asked for again. Same
    single answer, one enumeration per command instead of two.
    """

    if not endpoints:
        return None
    first = endpoints[0]
    return str(first["host"]), int(first["port"])
