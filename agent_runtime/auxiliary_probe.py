"""Provider-client construction accounting (the probe itself is upstream's ``aux_probe_mode``)."""
import threading

_client_construction_count = 0
_client_construction_lock = threading.Lock()


def _note_client_construction() -> None:
    """Count one real provider-client construction (test/pin seam).

    Covers the auxiliary-client construction seams: every module-level
    ``OpenAI(...)`` (they all resolve through the proxy below), the async
    client, and the Anthropic adapter client.
    """

    global _client_construction_count
    with _client_construction_lock:
        _client_construction_count += 1


def client_construction_count() -> int:
    """How many provider clients this process has constructed so far.

    The invariant worth pinning is a DELTA of zero across a capability check —
    a wall-clock assertion would rot on the first slow CI box.
    """

    with _client_construction_lock:
        return _client_construction_count
