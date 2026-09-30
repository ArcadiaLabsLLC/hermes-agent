"""Special-use host names fail fast in-process instead of waiting on this box's resolver.

A fixture base URL such as ``https://new.example.test`` or ``http://x`` can never
resolve, but Windows' resolver takes ~12 s to say so for a reserved TLD or a
single-label name (measured 2026-09-29: ``new.example.test``, ``foo.invalid``,
``example.test`` 12.1 s each, ``api.example.com`` 0.04 s). An upstream model-flow
test that probes such an endpoint (``agent.model_metadata._ollama_show``,
``detect_local_server_type``) then spends two or three lookups and meets the
fork's 30 s per-test cap, which kills the whole file (triage class E2,
``docs/downstream/triage-561-2026-09-29.md``).

The answer given here is the one the resolver gives eventually — ``gaierror``
``EAI_NONAME`` — only sooner. Every other name, and every IP literal, goes to the
real ``socket.getaddrinfo``. A test that patches ``socket.getaddrinfo`` itself
replaces this wrapper for its own body, as before.
"""

from __future__ import annotations

import socket

#: RFC 2606 / RFC 6761 reserved TLDs, plus ``.internal`` (ICANN, 2024).
_RESERVED_SUFFIXES = (".test", ".invalid", ".example", ".internal")

#: Placeholder hosts under REAL domains that upstream fixtures use and that answer
#: NXDOMAIN only after the same ~12 s wait (measured 2026-09-29). Exact names only:
#: a suffix here would swallow real endpoints of the same provider.
_PLACEHOLDER_HOSTS = frozenset({"placeholder.services.ai.azure.com"})


def is_reserved_name(host: object) -> bool:
    """True for a host name no resolver can answer: a reserved TLD, one label, or a known placeholder."""

    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str) or not host:
        return False
    name = host.rstrip(".").lower()
    if not name or ":" in name or name.replace(".", "").isdigit():
        return False  # IP literals
    if name in _PLACEHOLDER_HOSTS or name.endswith(_RESERVED_SUFFIXES) or name.lstrip(".") in {s[1:] for s in _RESERVED_SUFFIXES}:
        return True
    return "." not in name and name not in {"localhost", socket.gethostname().lower()}


def install() -> None:
    """Wrap ``socket.getaddrinfo`` once per process (idempotent)."""

    real = socket.getaddrinfo
    if getattr(real, "_fork_reserved_dns", False):
        return

    def getaddrinfo(host, *args, **kwargs):
        if is_reserved_name(host):
            raise socket.gaierror(socket.EAI_NONAME, f"reserved test host {host!r} (tests/_downstream/reserved_dns.py)")
        return real(host, *args, **kwargs)

    getaddrinfo._fork_reserved_dns = True  # type: ignore[attr-defined]
    getaddrinfo.__wrapped__ = real  # type: ignore[attr-defined]
    socket.getaddrinfo = getaddrinfo
