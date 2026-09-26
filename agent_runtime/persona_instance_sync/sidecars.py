"""The never-synced files: the baseline, the dropped-steering ledger, the conflict parking; and the pulled projection read.

Map: ``agent_runtime/persona_instance_sync/__init__.py``.
"""

from __future__ import annotations

import json
from typing import Any

from agent_runtime import yaml_io

from .contract import PROJECTION_RELATIVE_PATH
from .projection import PersonaInstanceProjection, read_projection_document

__layer__ = "stores"


# --- baseline sidecar (never synced, never published) ------------------------
#
# The one IO in this module, and it sits below the line on purpose: everything
# above is pure so the allowlist, the projection, the hash and the admission
# grammar stay unit-testable without a store. This is the same two-halves shape
# ``persona_config_sync`` has, for the same reason — one module per synced
# family beats a pure module and a sidecar module that can drift apart.


def read_persona_instance_baseline(realm_id: str) -> dict[str, str]:
    from .. import paths

    path = paths.persona_instance_baseline_path(realm_id)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return {str(k): str(v) for k, v in entries.items()} if isinstance(entries, dict) else {}


def write_persona_instance_baseline(realm_id: str, entries: dict[str, str]) -> None:
    from utils import atomic_json_write

    from .. import paths

    atomic_json_write(
        paths.persona_instance_baseline_path(realm_id),
        {"schema_version": 1, "entries": entries},
        indent=2,
        sort_keys=True,
    )


def read_dropped_steering_ledger(realm_id: str) -> dict[str, dict[str, Any]]:
    """Edges phase two dropped for an ABSENT PARENT, and what they were dropped
    against — ``{instance_id: {"parents": [...], "remote_hash": "..."}}``.

    The durable half of the heal (the H3 known gap, closed 2026-09-02). Read
    beside the baseline, written by the same pass, never synced and never
    published.

    A malformed or unreadable file yields ``{}``, and that is the safe
    direction: the ledger is a repair aid, so its failure mode must be "no heal
    is attempted", never "an edge is re-applied on the word of a body nobody can
    vouch for". Entries missing either half are dropped for the same reason —
    the parent alone cannot say whether the realm has moved since.
    """

    from .. import paths

    path = paths.persona_instance_dropped_steering_path(realm_id)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        return {}
    ledger: dict[str, dict[str, Any]] = {}
    for instance_id, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        parents = [str(item) for item in (entry.get("parents") or []) if item]
        remote_hash = entry.get("remote_hash")
        if not parents or not isinstance(remote_hash, str):
            continue
        ledger[str(instance_id)] = {"parents": parents, "remote_hash": remote_hash}
    return ledger


def write_dropped_steering_ledger(realm_id: str, entries: dict[str, dict[str, Any]]) -> None:
    """Replace the heal ledger with what the pass that just ran phase two saw.

    REBUILT, never merged, and that is what keeps it from rotting: an entry
    survives only while the same pass drops the same edge again, so a healed
    edge, a row the realm stopped carrying, a row that went to HOLD and a row
    whose remote body moved all clear themselves with no expiry rule and no
    second pruning walk. The two callers that return BEFORE phase two — an older
    peer's absent projection, and an unreadable one — deliberately do NOT call
    this: neither is evidence about a dropped edge, and forgetting every one of
    them on a single pull in a rotation would silently end the heal.
    """

    from utils import atomic_json_write

    from .. import paths

    atomic_json_write(
        paths.persona_instance_dropped_steering_path(realm_id),
        {"schema_version": 1, "entries": entries},
        indent=2,
        sort_keys=True,
    )


def instance_baseline_key(instance_id: str) -> str:
    """This family's baseline key. ``instance:<id>``, namespaced because the
    drift/revert lane addresses rows by ``FAMILY:CONTAINER:KEY`` and a bare id
    would be indistinguishable from a container token."""

    return f"instance:{instance_id}"


def instance_conflict_path(realm_id: str, instance_id: str):
    """Where a HELD row's remote body is parked.

    Under the realm-sync root, beside the baseline, so it is never-synced and
    never-published by construction. The office lane's ``conflicts/`` precedent:
    a hold that leaves no copy of what it refused to adopt makes the operator's
    only exit "pull again and hope".
    """

    from .. import paths

    return (
        paths.realm_sync_root()
        / paths.safe_path_token(realm_id)
        / "persona_instance_conflicts"
        / f"{paths.safe_path_token(instance_id)}.json"
    )


def update_persona_instance_baseline_after_publish(
    realm_id: str, projection: PersonaInstanceProjection
) -> None:
    """Record the published bodies' hashes as the new baseline.

    The ``_published_profile_file_hashes`` precedent: a member who publishes and
    then pulls must see local == baseline, or their own publish comes straight
    back as a HOLD on every row they just shipped.
    """

    baseline = read_persona_instance_baseline(realm_id)
    for instance_id, body_hash in projection.hashes().items():
        baseline[instance_baseline_key(instance_id)] = body_hash
    write_persona_instance_baseline(realm_id, baseline)


def read_remote_persona_instances(subtree) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Instance bodies carried by a pulled realm subtree.

    ``(bodies, source)``; ``source`` is ``None`` when the subtree has no
    projection — an older publisher, or a realm that publishes no
    placement-backed rows. There is deliberately NO legacy fallback: unlike
    persona definitions, instances have never travelled in any other shape, so
    an absent projection means exactly one thing.
    """

    from pathlib import Path

    path = Path(subtree).joinpath(*PROJECTION_RELATIVE_PATH.split("/"))
    if not path.is_file():
        return {}, None
    try:
        data = yaml_io.load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml_io.YAMLError):
        # A projection that exists and will not decode is NOT absence: absence
        # drives ``upstream_absent`` for every baselined row, and reading a parse
        # error as absence would be a delete-shaped decision taken on a read
        # failure (the ``RemoteOffice.unreadable`` argument). The caller reports
        # it as a refusal and touches nothing.
        return {}, "unreadable"
    parsed = read_projection_document(data)
    if parsed is None:
        return {}, None
    return parsed, "projection"
