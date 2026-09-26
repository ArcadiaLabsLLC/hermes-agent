"""Address arithmetic and the dial-failure vocabulary (R-D2, R-D20) — no I/O.

The offer filter, the RFC1918 / same-/24 / same-/64 tests, the dial-order
rank, and the two R-D20 words with the errno sets that decide them.
Moved DOWN out of ``hermes_cli.harness_parts.gateway_commands`` (layout sheet
gateway_commands.md §1): nothing in this package imports ``hermes_cli``.
"""

from __future__ import annotations

import errno

__layer__ = "policy"


#: Addresses this machine offers a peer, capped at ``gateway_peers.MAX_ENDPOINTS``.
#: Not a config knob: the cap is the peer row's, and a list longer than the row
#: can hold would advertise addresses that silently vanish at the far end.
MAX_CANDIDATE_ENDPOINTS = 4

#: Hosts that are never worth offering another machine. Loopback is this box
#: talking to itself, link-local is an address that only means something on the
#: segment that assigned it, and a wildcard is a BIND and not an address at all.
#: Prefixes rather than a netmask calculation, because this is a filter over
#: strings the stdlib handed us, and half an address library here would be a
#: second address model to keep true.
_UNOFFERABLE_PREFIXES = ("127.", "169.254.", "fe80:")
_WILDCARD_HOSTS = {"0.0.0.0", "::", "*", ""}

#: RFC1918, written out. The filter above is deliberately prefix-based ("half an
#: address library here would be a second address model to keep true") but the
#: ORDER needs real arithmetic — "shares a /24 with the default route" is not a
#: string test — so the ordering asks the stdlib's address library rather than
#: growing a second one out of octet slicing.
_RFC1918_CIDRS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")


def _ipv4(host: str):
    """The host as an ``IPv4Address``, or ``None`` if it is not one.

    ``None`` for every v6 address and for anything that will not parse, because
    both answers mean the same thing to the ranking below: this row is not a
    private-LAN candidate and cannot share a /24 with one.
    """

    import ipaddress

    try:
        address = ipaddress.ip_address(str(host))
    except ValueError:
        return None
    return address if address.version == 4 else None


def _is_rfc1918(host: str) -> bool:
    import ipaddress

    address = _ipv4(host)
    if address is None:
        return False
    return any(
        address in ipaddress.ip_network(cidr) for cidr in _RFC1918_CIDRS
    )


def _shares_24(host: str, other: str) -> bool:
    left, right = _ipv4(host), _ipv4(other)
    if left is None or right is None:
        return False
    return int(left) >> 8 == int(right) >> 8


def _address_rank(
    host: str, default_route: str | None, table_route: str | None = None
) -> int:
    """R-D2's order with R-D8 in front of it, as a sort key. Lower dials first.

    0. **The routing table's owner of ``0.0.0.0/0``** (R-D8). The one source
       that can tell a LAN apart from a full-tunnel VPN, because the VPN's
       ``/1`` pair is what the probe below follows.
    1. **The probe's answer** — the address traffic actually leaves from. First
       until D1b, and still first whenever the table declines to answer.
    2. **RFC1918 addresses on the default route's own /24.** A second address on
       the same segment is the next best guess when the first is filtered by a
       firewall rule that does not cover the whole subnet.
    3. **Other RFC1918.** A private address somewhere, which is what a LAN peer
       is most likely to be able to reach.
    4. **Everything else v4** — a public address, and the Hamachi/Tailscale-class
       overlays that hand out addresses outside 1918. Sorted here BY RULE and
       not filtered by adapter name (R-D2): a machine whose only address is one
       of those still gets offered, because refusing to offer it would make an
       overlay-only machine unpairable in the name of tidiness.
    5. **Global v6**, last: a v6 address that works is excellent and a v6
       address that does not is a dial that hangs before the v4 one is tried.

    The /24 arithmetic follows whichever of the two sources came first, so on a
    VPN'd machine "the default route's own subnet" means the LAN's subnet and
    not the tunnel's — the ranks below 2 would otherwise contradict rank 0.
    """

    if table_route and host == table_route:
        return 0
    if default_route and host == default_route:
        return 1
    if ":" in host:
        return 5
    primary = table_route or default_route
    if _is_rfc1918(host):
        return 2 if primary and _shares_24(host, primary) else 3
    return 4


#: R-D20's two words. ``local_policy`` is *this* machine's OS refusing to put a
#: packet on its own network; ``unreachable`` is everything else a dial can be —
#: a listener that is down, a firewall that dropped the SYN, an address nobody
#: routes to. They are separate because the operator's next MOVE differs: one is
#: a permission granted here, the other is a retry or a trip to the far machine.
DIAL_LOCAL_POLICY = "local_policy"
DIAL_UNREACHABLE = "unreachable"

#: ``WSAEHOSTUNREACH``. Windows delivers it in ``OSError.winerror`` and
#: translates ``errno`` to the CRT's own ``EHOSTUNREACH`` (110), so both fields
#: have to be read; the POSIX numbers are written out beside
#: :data:`errno.EHOSTUNREACH` for the same reason a test on Windows must be able
#: to present the Mac's 65 — the errno of the kernel that refused is not always
#: the errno of the interpreter reading it (an exception can arrive from a
#: proxied dial, and every fixture in this repo runs on one platform).
_WSAEHOSTUNREACH = 10065
_HOST_UNREACHABLE_ERRNOS = frozenset(
    {errno.EHOSTUNREACH, 65, 113, _WSAEHOSTUNREACH}
)

#: IPv6 prefixes that are on-link BY DEFINITION or by convention: link-local
#: (``fe80::/10``, meaningful only on the segment that assigned it) and the
#: unique-local range (``fc00::/7``), which is v6's RFC1918. A GLOBAL v6 address
#: is deliberately absent: without the prefix LENGTH the kernel assigned there
#: is no honest way to say whether it shares a segment with us, and R-D20 only
#: ever wants to be sure in one direction.
_V6_LINK_LOCAL = "fe80::/10"
_V6_UNIQUE_LOCAL = "fc00::/7"


def _in_network(host: str, cidr: str) -> bool:
    import ipaddress

    try:
        return ipaddress.ip_address(str(host)) in ipaddress.ip_network(cidr)
    except ValueError:
        return False


def _shares_64(host: str, other: str) -> bool:
    """The v6 twin of :func:`_shares_24`, for the unique-local case."""

    import ipaddress

    try:
        left = ipaddress.ip_address(str(host))
        right = ipaddress.ip_address(str(other))
    except ValueError:
        return False
    if left.version != 6 or right.version != 6:
        return False
    return int(left) >> 64 == int(right) >> 64


#: The sentence R-D20 owes the operator, and the interface D6l maps onto
#: ``MissionPairingReason.localNetworkDenied``. Written once because both dial
#: doors print it and a second spelling is a second contract.
LOCAL_POLICY_SENTENCE = (
    "this machine's operating system refused to send to a host on its own "
    "network — on macOS allow this app under System Settings › Privacy & "
    "Security › Local Network"
)
