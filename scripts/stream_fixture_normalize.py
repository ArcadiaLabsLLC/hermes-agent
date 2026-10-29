"""Volatile-value normalization for the stream goldens
``generate_agent_runtime_stream_fixtures.py`` writes — kept here so that generator
stays under the downstream size ceiling. ``tests/agent_runtime/test_serve_stream_lane_parity.py``
reaches ``_normalize`` through the generator's import of it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXED_TIME = "2026-07-16T12:00:00.000000Z"

#: Synthetic event-log positions for the agent-create pair, in order:
#: ``base_offset`` first, then one per batched event.
#:
#: **Why these are pinned and the other goldens' offsets are not.** Every other
#: generated frame's offsets are real byte positions in a log whose only entries
#: are two ``state.reconciled`` events with fixed payloads, so they reproduce
#: anywhere. A CREATE's events embed absolute paths — ``runtime_root`` on the
#: roster patch, ``chat_head_home`` on ``persona_instance.chat_opened`` — so the
#: log's byte positions are a function of where the generating machine puts its
#: temporary directory. That is the same class of machine-dependence
#: :data:`_MACHINE_PROBED_FLAGS` retires, and it is retired the same way.
#:
#: What the frames CONTRACT is the ORDER and the strict inequalities —
#: ``base_offset`` < every ``seq`` < ``watermark.event_offset`` — because the
#: launcher folds only when its held watermark equals ``base_offset`` and its
#: sequence gate is strict ``>``. Magnitudes say nothing to either repo. The
#: stride is deliberately round so nobody mistakes them for measured sizes.
_FIXTURE_CREATE_OFFSET_BASE = 4096
_FIXTURE_CREATE_OFFSET_STRIDE = 512


_TIME_KEYS = {
    "generated_at",
    "captured_at",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "last_heartbeat_at",
}
_VOLATILE_METRICS = {
    "build_ms",
    "snapshot_bytes",
    "event_log_bytes",
    "projection_age_ms",
    # running_work row fields that answer questions about THIS run rather than
    # about the contract: the generator's own OS process id, and seconds counted
    # from a fixed spawn stamp to whenever the script happened to execute. Both
    # would otherwise change the committed bytes on every regeneration. The
    # honesty fields beside them — `pid_verified`, `status` — are deliberately
    # NOT normalized: the seed pins them by construction (a NULL spawn baseline
    # is unprovable identity, so the row is `unknown`/`pid_verified: false` on
    # every platform), which is what makes those two bytes reviewable.
    "pid",
    "elapsed_seconds",
}
_VOLATILE_METRIC_MAPS = {
    # Each section is timed independently while the parity snapshot is built.
    # Normalizing only the container key keeps configured/contractual durations
    # elsewhere in the frame intact while removing scheduler and filesystem
    # jitter from every current and future section name.
    "sections_ms",
}
_MACHINE_PROBED_FLAGS = {
    # container key -> (per-entry flag key, pinned value)
    #
    # The ONE value in the frame that answers a question about the operator's
    # DISK rather than about the isolated runtime root. See the module docstring
    # for the full derivation: `repo_scopes[*].resolved` is a probe of
    # machine-local root bindings, so without this pin the script emits
    # different bytes on a configured operator box and an isolated generator.
    #
    # Only the flag is pinned. `label` is contractual and survives untouched, so
    # this stays a normalization rather than a rewrite of the section.
    "repo_scopes": ("resolved", True),
}


#: Keys whose integer value is an EVENT-LOG BYTE POSITION.
#:
#: Only consulted when a caller passes an ``offset_map`` (today: the
#: agent-create pair, whose events embed absolute paths — see
#: :data:`_FIXTURE_CREATE_OFFSET_BASE`). Every other generated frame's offsets
#: are already machine-independent and are left exactly as the producer built
#: them.
_OFFSET_KEYS = {"event_offset", "base_offset", "seq"}

#: Wall-clock stamps that are volatile for SOME frames and CONTRACTUAL for
#: others, so they can never join :data:`_TIME_KEYS`.
#:
#: ``delta.json`` / ``delta_batch.json`` seed their events with fixed stamps one
#: second apart, and the ONE-second gap is the batch's own evidence that it
#: coalesced two distinct events — folding both onto :data:`FIXED_TIME` would
#: erase it. A frame built off a REAL store write has no such luxury: its
#: ``ts`` is whenever the generator ran. So the two keys are opt-in per frame.
_OPTIONAL_TIME_KEYS = frozenset({"ts", "last_event_ts"})


def _normalize(
    value: Any,
    *,
    isolated_root: Path,
    key: str = "",
    time_keys: frozenset[str] = frozenset(),
    pinned_values: dict[str, Any] | None = None,
    offset_map: dict[int, int] | None = None,
) -> Any:
    """Volatile values out, contract in.

    ``time_keys`` adds to :data:`_TIME_KEYS` for THIS frame only (see
    :data:`_OPTIONAL_TIME_KEYS`); ``pinned_values`` replaces a key's whole value
    with a fixture constant (the generator's ``_REGISTRY_PROBED_VALUES``); ``offset_map``
    rewrites event-log byte positions through a rank map (see
    :data:`_FIXTURE_CREATE_OFFSET_BASE`). All three default to "do nothing", so
    every frame that predates them normalizes byte-identically.
    """

    forward = dict(
        isolated_root=isolated_root,
        time_keys=time_keys,
        pinned_values=pinned_values,
        offset_map=offset_map,
    )
    if pinned_values is not None and key in pinned_values:
        return json.loads(json.dumps(pinned_values[key]))
    if (
        offset_map is not None
        and key in _OFFSET_KEYS
        and isinstance(value, int)
        and not isinstance(value, bool)
    ):
        if value not in offset_map:
            raise AssertionError(
                f"offset {value!r} under key {key!r} was not collected by "
                "_offset_rank_map, so this frame carries a byte position the "
                "pin cannot reach and the golden would churn per machine"
            )
        return offset_map[value]
    if isinstance(value, dict):
        if key in _VOLATILE_METRIC_MAPS:
            return {str(item_key): 0 for item_key in value}
        normalized = {
            str(item_key): _normalize(item, key=str(item_key), **forward)
            for item_key, item in value.items()
        }
        if key == "runtime_root" and "fingerprint" in normalized:
            normalized["fingerprint"] = "isolated-runtime"
        if key in _MACHINE_PROBED_FLAGS:
            flag_key, pinned = _MACHINE_PROBED_FLAGS[key]
            for entry in normalized.values():
                if isinstance(entry, dict) and flag_key in entry:
                    entry[flag_key] = pinned
        return normalized
    if isinstance(value, list):
        return [_normalize(item, **forward) for item in value]
    if (key in _TIME_KEYS or key in time_keys) and value is not None:
        return FIXED_TIME
    if key in _VOLATILE_METRICS and value is not None:
        return 0
    if isinstance(value, str):
        root = str(isolated_root)
        redacted = value.replace(root, "<isolated-root>").replace(root.replace("\\", "/"), "<isolated-root>")
        if redacted == value:
            return value
        # The ROOT is redacted; the TAIL after the placeholder was not, so it
        # carried the separator of whichever host last regenerated —
        # `<isolated-root>\\runtime` from Windows, `<isolated-root>/runtime`
        # from Linux. That made these goldens regenerable only on the box that
        # last wrote them: `test_committed_goldens_are_the_generators_bytes`
        # was green on Windows and red on every Linux runner, and the
        # launcher's byte-identical vendored copies inherited the same
        # Windows-shaped bytes. A cross-repo, cross-OS byte pin cannot carry
        # the generating machine's path syntax, so the redacted spelling is
        # canonicalised to forward slashes. Only strings that actually held the
        # isolated root are touched.
        return redacted.replace("\\", "/")
    return value


def _offset_rank_map(*frames: Any) -> dict[int, int]:
    """Every event-log byte position in ``frames``, ranked onto a fixed lattice.

    Ranked BY VALUE across the whole pair at once, so the two frames stay
    mutually consistent: the patch frame's ``base_offset`` and the demoted
    frame's ``watermark.event_offset`` describe the same batch and must not be
    pinned by two independent passes.
    """

    found: set[int] = set()

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for item_key, item in value.items():
                walk(item, str(item_key))
        elif isinstance(value, list):
            for item in value:
                walk(item, key)
        elif key in _OFFSET_KEYS and isinstance(value, int) and not isinstance(value, bool):
            found.add(value)

    for frame in frames:
        walk(frame)
    return {
        real: _FIXTURE_CREATE_OFFSET_BASE + _FIXTURE_CREATE_OFFSET_STRIDE * rank
        for rank, real in enumerate(sorted(found))
    }
