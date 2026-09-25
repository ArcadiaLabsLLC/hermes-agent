"""The two pure halves: the publish projection (+ its hash) and the pull admission door.

Map: ``agent_runtime/persona_instance_sync/__init__.py``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields
from datetime import datetime
from functools import singledispatch
from typing import Any

import yaml

from ..models import looks_like_persona_instance_id
from .contract import (
    PERSONA_INSTANCE_ALLOWED_KEYS,
    PROJECTION_KIND,
    PROJECTION_SCHEMA_VERSION,
    REFUSAL_CANONICAL_CHANNEL,
    REFUSAL_INCOMPLETE,
    REFUSAL_INVALID_INSTANCE_ID,
    REFUSAL_STEERING_SHAPE,
    REFUSAL_UNEXPECTED_KEY,
)

__layer__ = "policy"


# --- projection ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PersonaInstanceProjection:
    """The synthesized, publishable persona-instance document.

    ``instances`` is the pruned + allowlisted map. Everything else is accounting,
    on the ``PersonaConfigProjection.dropped_keys`` precedent — a publish must
    never be able to ship a partial record and report a clean result.

    - ``dropped_keys`` — every field the allowlist removed, as a dotted path.
      ``runtime_root`` appears here on every publish, and that is the point: the
      most portability-hostile field on the record is reported as withheld
      rather than silently absent.
    - ``skipped_canonical`` — ids excluded because they ARE the persona's
      canonical operator channel. Not a refusal: every machine derives its own,
      so withholding them is the scoping ruling working (plan §2).
    - ``refused`` — records this machine would not project: a travelling field
      holding a machine-shaped value, or an id that is not instance-shaped. Rows
      are ``{key, code, message}``, the shared ``Refusal`` shape.
    - ``missing`` — wanted ids with no resolvable record.
    """

    instances: dict[str, dict[str, Any]] = field(default_factory=dict)
    dropped_keys: list[str] = field(default_factory=list)
    skipped_canonical: list[str] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def document(self) -> dict[str, Any]:
        return {
            "instances": self.instances,
            "kind": PROJECTION_KIND,
            "schema_version": PROJECTION_SCHEMA_VERSION,
        }

    def to_bytes(self) -> bytes:
        """Deterministic bytes: sorted keys, block style, LF. Republishing an
        unchanged projection is a byte-for-byte no-op, so the publish
        change-detector (``_published_artifacts_differ``) stays honest."""

        text = yaml.safe_dump(
            self.document(),
            sort_keys=True,
            default_flow_style=False,
            allow_unicode=True,
            width=4096,
        )
        return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")

    def hashes(self) -> dict[str, str]:
        return {
            instance_id: persona_instance_def_hash(body)
            for instance_id, body in self.instances.items()
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "instances": sorted(self.instances),
            "dropped_keys": sorted(set(self.dropped_keys)),
            "skipped_canonical": sorted(set(self.skipped_canonical)),
            "refused": list(self.refused),
            "missing": sorted(set(self.missing)),
        }


def persona_instance_def_hash(body: Any) -> str:
    """Semantic content hash of one projected instance (key-order independent).

    Nothing timestamp-shaped is in the projection except
    ``model_override_issued_at``, which is DELIBERATELY hashed: it is the
    supersession clock for the override tier, so a body whose clock moved is a
    body that changed. ``updated_at`` — the local write clock — never enters,
    for the reason ``office_models._HASH_EXCLUDE`` states.
    """

    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@singledispatch
def _wire_value(value: Any) -> Any:
    """One field as it travels: plain YAML/JSON scalars and containers only.

    A strategy by type (rule 12): each shape that may travel is a registration
    below. ``datetime`` is rendered through ``serde.to_jsonable``'s spelling
    (ISO-8601 microseconds, ``Z``) rather than refused, because
    ``model_override_issued_at`` MUST travel and ``from_jsonable`` parses exactly
    that shape back. Anything else exotic lands HERE, raises ``TypeError`` and is
    dropped with accounting — determinism is load-bearing for the change
    detector and the content hash, which is also why this is not
    ``serde.to_jsonable`` (it neither sorts dict keys nor refuses).
    """

    raise TypeError(type(value).__name__)


@_wire_value.register(datetime)
def _wire_datetime(value: datetime) -> str:
    from ..serde import to_jsonable

    return to_jsonable(value)


@_wire_value.register(type(None))
@_wire_value.register(str)
@_wire_value.register(bool)
@_wire_value.register(int)
@_wire_value.register(float)
def _wire_scalar(value: Any) -> Any:
    return value


@_wire_value.register(list)
@_wire_value.register(tuple)
def _wire_sequence(value: list | tuple) -> list[Any]:
    return [_wire_value(item) for item in value]


@_wire_value.register(dict)
def _wire_mapping(value: dict) -> dict[str, Any]:
    return {str(key): _wire_value(item) for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}


def project_persona_instance(record: Any, *, dropped: list[str] | None = None) -> dict[str, Any]:
    """Project ONE persona-instance record through the allowlist.

    Field names come FROM the record (dataclass fields when it is one), never
    from a hard-coded list — the ``_record_field_names`` precedent, and what
    keeps a newly added ``PersonaInstance`` field accounted as a drop the day it
    lands rather than silently invisible.

    ``None`` and structurally-empty values are omitted: on this record ``None``
    means "inherit" for the override tier and "runtime-global" for the scope
    pointers, so writing the absence would only make two equivalent bodies hash
    differently. ``id`` and ``persona_id`` are always present — they are the
    merge key and the definition pointer.
    """

    accounting = dropped if dropped is not None else []
    instance_id = str(getattr(record, "id", "") or "")
    try:
        names = sorted(item.name for item in fields(record))
    except TypeError:
        names = sorted(name for name in dir(record) if not name.startswith("_"))
    body: dict[str, Any] = {}
    for name in names:
        if name not in PERSONA_INSTANCE_ALLOWED_KEYS:
            accounting.append(f"instances.{instance_id}.{name}")
            continue
        value = getattr(record, name, None)
        if name not in ("id", "persona_id") and (value is None or value == [] or value == {}):
            continue
        try:
            body[name] = _wire_value(value)
        except TypeError:
            accounting.append(f"instances.{instance_id}.{name}")
    return body


def project_persona_instances(
    instance_ids: list[str] | set[str],
    *,
    records: dict[str, Any] | None = None,
) -> PersonaInstanceProjection:
    """Build the portable projection for exactly ``instance_ids``.

    Pruning to the wanted set is part of the contract: the projection must carry
    the instances the published office actors actually reference and nothing
    else. ``realm_sync._office_publish_scan`` resolves that set in the SAME walk
    that resolves the persona ids — one walk, one authority — because a second
    glob is how the artifact list and the persona list came apart last time.

    Two exclusions, and they are different facts:

    * a CANONICAL channel row is skipped (``skipped_canonical``). Every member
      derives its own; publishing one would be a peer asserting a row the
      receiver's own ``ensure_for_personas`` already owns.
    * a record whose projected body still carries a machine-shaped value is
      REFUSED (``nonportable_path``). Withholding ``runtime_root`` is the
      allowlist's job; catching an absolute path that reached the wire through
      an authored ``display_name`` is this one's.
    """

    from ..persona_assignments.identity import is_canonical_persona_channel
    from ..persona_config_sync import find_nonportable_values

    records = records or {}
    instances: dict[str, dict[str, Any]] = {}
    dropped: list[str] = []
    skipped_canonical: list[str] = []
    refused: list[dict[str, str]] = []
    missing: list[str] = []
    for instance_id in sorted({str(item) for item in instance_ids}):
        record = records.get(instance_id)
        if record is None:
            missing.append(instance_id)
            continue
        if not valid_persona_instance_id(instance_id):
            refused.append(
                {
                    "key": instance_id,
                    "code": REFUSAL_INVALID_INSTANCE_ID,
                    "message": "instance id is not a safe persona-instance path token",
                }
            )
            continue
        try:
            if is_canonical_persona_channel(record):
                skipped_canonical.append(instance_id)
                continue
        except Exception:  # noqa: BLE001 — a record that cannot answer is not projectable
            refused.append(
                {
                    "key": instance_id,
                    "code": REFUSAL_INCOMPLETE,
                    "message": "record could not be classified against the canonical channel",
                }
            )
            continue
        body = project_persona_instance(record, dropped=dropped)
        if not body.get("persona_id"):
            refused.append(
                {
                    "key": instance_id,
                    "code": REFUSAL_INCOMPLETE,
                    "message": "record carries no persona_id to build from",
                }
            )
            continue
        offenders = find_nonportable_values(body, prefix=f"instances.{instance_id}")
        if offenders:
            refused.append(
                {
                    "key": instance_id,
                    "code": "nonportable_path",
                    "message": "machine-shaped value(s): "
                    + ", ".join(row["key"] for row in offenders),
                }
            )
            continue
        instances[instance_id] = body
    return PersonaInstanceProjection(
        instances=instances,
        dropped_keys=sorted(set(dropped)),
        skipped_canonical=sorted(set(skipped_canonical)),
        refused=refused,
        missing=sorted(set(missing)),
    )


def read_projection_document(data: Any) -> dict[str, dict[str, Any]] | None:
    """Parse a pulled ``store/persona_instances.yaml`` document.

    ``None`` means "this subtree carries no instance projection" — an older
    publisher, or a realm that publishes no placement-backed rows. Absence is
    never a removal (plan §3.3 ``upstream_absent``), and the caller keys its
    whole version-skew story on this distinction.
    """

    if not isinstance(data, dict) or data.get("kind") != PROJECTION_KIND:
        return None
    raw = data.get("instances")
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


# --- admission (plan §4) ------------------------------------------------------


def instance_relative_path(instance_id: str) -> str:
    """The relative path an instance row occupies under the store root.

    Synthesized so the SHARED ``sync_admission.path_refusal`` — which already
    covers traversal, absolute/drive-letter/UNC shapes and Windows reserved
    device names — can be asked about an untrusted id, rather than this lane
    growing a second spelling of those rules.
    """

    return f"persona_instances/{instance_id}.json"


def valid_persona_instance_id(instance_id: str) -> bool:
    """Is this id both instance-shaped and safe as its own filename?

    The second half is the load-bearing one and it is asked by ROUND-TRIP rather
    than by regex: ``paths.persona_instance_path`` writes through
    ``safe_path_token``, so an id that token would rewrite is an id whose row
    lands under a key that is NOT the key the realm agreed on — the merge unit
    silently renamed, which is exactly the non-convergence Option B was refused
    for. Asking the real sanitizer instead of a second pattern means the two can
    never disagree.
    """

    from .. import paths
    from ..sync_admission import path_refusal

    text = str(instance_id or "")
    if not looks_like_persona_instance_id(text):
        return False
    if paths.safe_path_token(text) != text:
        return False
    return path_refusal(instance_relative_path(text)) is None


def refuse_persona_instance(instance_id: str, body: Any):
    """One admission decision for one pulled instance row, or ``None``.

    Order is deliberate: the ID first (a body keyed by an unsafe id has nothing
    worth scanning), then the SHARED ``sync_admission`` door — secret-shaped
    assignments through BOTH scanner passes and the machine-shaped-value walk —
    and only then the three rules this family adds on top of it. That ordering
    is what makes the plan's §4 table literally true: a ``runtime_root`` in the
    body reports ``nonportable_path`` (the door saw it first) while a
    ``session_id`` reports ``unexpected_key`` (nothing shared objects to it).

    ``prose_keys=frozenset()`` because an instance body is 100% wiring — its
    keys ARE an allowlist — so nothing here is exempt prose, the persona-
    definition lane's argument for the same choice.

    Per-entity isolation: the caller refuses THIS row, names it, and keeps
    pulling.
    """

    from ..persona_assignments.identity import persona_instance_id_for
    from ..sync_admission import Refusal, refuse_entity

    if not valid_persona_instance_id(instance_id):
        return Refusal(
            instance_id,
            REFUSAL_INVALID_INSTANCE_ID,
            f"not a safe persona-instance id: {instance_id!r}",
        )
    if not isinstance(body, dict):
        return Refusal(instance_id, REFUSAL_INCOMPLETE, "instance body is not a mapping")

    refusal = refuse_entity(
        instance_id,
        payload=body,
        prefix=f"instances.{instance_id}",
        prose_keys=frozenset(),
    )
    if refusal is not None:
        return refusal

    unexpected = sorted(str(key) for key in body if str(key) not in PERSONA_INSTANCE_ALLOWED_KEYS)
    if unexpected:
        return Refusal(
            instance_id,
            REFUSAL_UNEXPECTED_KEY,
            "key(s) outside the instance allowlist: " + ", ".join(unexpected),
        )

    persona_id = str(body.get("persona_id") or "")
    declared_id = str(body.get("id") or "")
    if not persona_id or not declared_id:
        return Refusal(
            instance_id, REFUSAL_INCOMPLETE, "instance body carries no id/persona_id"
        )
    if declared_id != instance_id:
        return Refusal(
            instance_id,
            REFUSAL_INVALID_INSTANCE_ID,
            f"body id {declared_id!r} disagrees with its published key",
        )
    if instance_id == persona_instance_id_for(persona_id):
        return Refusal(
            instance_id,
            REFUSAL_CANONICAL_CHANNEL,
            (
                f"{instance_id} is the canonical operator channel for {persona_id!r}; "
                "canonical rows are derived locally on every machine and never replicate"
            ),
        )

    steered_by = body.get("steered_by")
    if steered_by is not None:
        if not isinstance(steered_by, list) or not all(
            looks_like_persona_instance_id(item) for item in steered_by
        ):
            return Refusal(
                instance_id,
                REFUSAL_STEERING_SHAPE,
                "steered_by must be a list of persona-instance ids",
            )
    return None
