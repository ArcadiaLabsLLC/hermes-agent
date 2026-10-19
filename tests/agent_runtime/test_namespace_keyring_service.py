"""The macOS/Linux secure-store service carries the namespace id (row RT-NAMESPACE-KEYRING-SERVICE).

The keyring slot (``binding.slot``: ``<prefix>/<profile>/<relative>``) holds no root, so the
service is the only thing that can keep two namespaces of one OS user apart.
"""

from __future__ import annotations

from agent_runtime.host_store import desktop

SLOT = "hermes/base/auth.json"  # the same profile-relative slot in every namespace


class _Backend:
    """An in-memory keyring keyed exactly as the real one is: (service, username)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str):
        return self.rows.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.rows[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        del self.rows[(service, username)]


def test_two_namespaces_write_one_slot_and_each_reads_its_own(monkeypatch):
    backend = _Backend()
    monkeypatch.setattr(desktop, "admitted_keyring_backend", lambda load_keyring=None: backend)
    stores = {}
    for ns_id in ("acct-0123456789abcdef", "acct-fedcba9876543210"):
        monkeypatch.setenv("HERMES_NAMESPACE", ns_id)
        stores[ns_id] = desktop._keyring_store("unused")
        stores[ns_id].write(SLOT, ns_id.encode())
    for ns_id, store in stores.items():
        assert store.service == f"hermes-agent/{ns_id}"
        assert store.read(SLOT) == ns_id.encode()
    assert len(backend.rows) == 2


def test_the_base_root_keeps_the_unnamespaced_service(monkeypatch):
    for value in (None, "base"):
        if value is None:
            monkeypatch.delenv("HERMES_NAMESPACE", raising=False)
        else:
            monkeypatch.setenv("HERMES_NAMESPACE", value)
        assert desktop.keyring_service() == desktop.KEYRING_SERVICE == "hermes-agent"
