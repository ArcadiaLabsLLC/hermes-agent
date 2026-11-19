"""The phone's TLS trust anchors: certifi's bundle, named once, before any HTTPS client exists.

``agent.ssl_verify.install_truststore`` points every default ``SSLContext`` at the OS trust store
through ``truststore``, which sends every OS that is not Windows or macOS — Android and iOS
included (``platform.system()`` is ``"Android"`` / ``"iOS"``) — to its OpenSSL arm. That arm
trusts OpenSSL's compiled-in default file or directory, else the first of a short list of Linux
bundle files (read in the locked truststore 0.10.5, ``truststore/_openssl.py``). A phone has none
of them: Android keeps its roots in ``/system/etc/security/cacerts`` (named by OpenSSL's old
subject hash, which its directory lookup does not match — Android's layout, not read on a device),
and iOS keeps them only in Security.framework. So the phone's store is empty and every HTTPS call is refused (row
RT-PHONE-TLS-TRUST-UNPROVEN; read in code, not reproduced on a phone).

:func:`ensure_phone_tls_trust` exports ``SSL_CERT_FILE`` as certifi's bundle on Android and iOS.
That one variable reaches every path a TLS client takes: OpenSSL's default verify paths (the stdlib
``load_default_certs`` and truststore's OpenSSL arm both read it), and
``agent.ssl_verify.resolve_httpx_verify``, which hands httpx the platform context when it is set.
certifi ships in the phone bundle because httpx imports it. A host that already set
``SSL_CERT_FILE`` or ``SSL_CERT_DIR`` keeps its choice; off a phone it does nothing.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Callable, MutableMapping, Optional

__layer__ = "lanes"

__all__ = ["PHONE_PLATFORMS", "ensure_phone_tls_trust"]

logger = logging.getLogger(__name__)

#: ``sys.platform`` on CPython's Android and iOS builds (3.13+).
PHONE_PLATFORMS = frozenset({"android", "ios"})


def _certifi_bundle() -> Optional[str]:
    from agent.ssl_verify import certifi_bundle_path

    return certifi_bundle_path()


def ensure_phone_tls_trust(*, platform: str | None = None,
                           environ: MutableMapping[str, str] | None = None,
                           bundle: Callable[[], Optional[str]] = _certifi_bundle) -> Optional[str]:
    """Export ``SSL_CERT_FILE`` as certifi's bundle on a phone; -> the path exported, else ``None``.

    ``platform`` overrides ``sys.platform`` and ``environ`` ``os.environ`` (tests). Idempotent.
    """
    env = os.environ if environ is None else environ
    if (platform or sys.platform) not in PHONE_PLATFORMS:
        return None
    if env.get("SSL_CERT_FILE", "").strip() or env.get("SSL_CERT_DIR", "").strip():
        return None  # the host named its own anchors
    path = bundle()
    if not path or not Path(path).is_file():
        logger.warning("phone TLS trust: certifi's CA bundle is missing; every HTTPS call will be refused")
        return None
    env["SSL_CERT_FILE"] = path
    return path
