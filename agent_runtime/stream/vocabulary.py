"""The stream's vocabulary and coercions: the two schema versions, the default
caller, the demote batch reason, the deferral bound and its poll, the
fold-variants frame type, the batch cap, the cancel poll, the package logger,
``_redaction_safe_json`` and ``_first_text``.

A vocabulary module (sheet ``stream.md`` §1): exempt from the 100-line floor."""

from __future__ import annotations

import logging
from typing import Any

from ..redaction import ENV_SECRET_ASSIGNMENT_RE, scrub_tree
from ..serde import optional_text, to_jsonable

__layer__ = "models"

#: The package's one logger, under the name the single file logged as —
#: operator greps and the tests' ``record.name`` filters key on it.
logger = logging.getLogger("agent_runtime.stream")


STREAM_SCHEMA_VERSION = 1

#: S7-A: the op-based ``patch`` frame is the v2 stream frame. It ships ALONGSIDE
#: the v1 full-core frames (hydrate + uncovered/resync delta batches) — the plan
#: staged this additive, exactly as W1 staged coalescing: a v1 consumer keeps
#: reading full cores; a v2-aware consumer folds patch frames. Each patch entry
#: carries ``{seq, ts, entity, id, op, changed?}`` (op ∈ upsert/remove/refresh —
#: the producer's WIRE-LEVEL contract). The existing frame builders stay
#: ``schema_version 1`` so flag-off behavior is byte-identical (Ruling 0: the
#: flag is a new-lane activation gate, not an old-shape toggle).
STREAM_PATCH_SCHEMA_VERSION = 2


# Single-homed in ``agent_runtime.redaction`` — see the header there for the
# JSON blind spot every local spelling shared. group(1) is still the full key,
# so the ``f"{match.group(1)}=[redacted]"`` rebuild below is unchanged.
_SECRET_ASSIGNMENT_RE = ENV_SECRET_ASSIGNMENT_RE


#: The CLI stream command is the caller a ``stream_frames`` with nothing
#: threaded through it is: ``hermes harness stream`` on a terminal. The serve
#: hub names itself ``hub`` explicitly (``serve.py``'s producer factory) — the
#: default is not a guess about who is asking, it is the historical answer.
DEFAULT_STREAM_CALLER = "cli"


#: The ``reason=`` a batch bills when the patch lane could not express it and a
#: foldable update paid for a whole snapshot — the case worth grepping for, and
#: the ONLY lane :mod:`agent_runtime.demote_core_reuse` participates in. A
#: constant rather than a literal at both sites because the reuse gate and the
#: receipt must name the same lane: a resync is a re-baseline the client asked
#: for and a ``full_core`` is what every batch is with the patch lane off, and
#: neither is a repeated build of state somebody already built.
BATCH_REASON_DEMOTE = "demote"


#: Stage 5 (``planned/chat-turn-prep-cost.md`` §5): the HARD ceiling, in
#: milliseconds, on how long ONE demote-cadence core build may stand aside for
#: a live agent run.
#:
#: A module constant and not a config field ON PURPOSE — Stage 2 §7 records why:
#: every ``PersonaChatConfig``/runtime-config field is projected onto the
#: read-model wire, so a knob here reds the stream-contract goldens and becomes
#: a cross-stack landing. The value a knob would carry is a doctrine, and the
#: doctrine is written here instead.
#:
#: WHY BOUNDED AT ALL. The launcher's HUD freshness rides these builds; an
#: unbounded "wait until no turn is running" is a STARVATION on exactly the
#: install this exists for, where an operator sends turns back to back and the
#: demote lane would never see a quiet moment. The plan's own wording is
#: "hundreds of ms, not a starvation". The bound is the ceiling on the WHOLE
#: deferral of one build request, not per poll: once it elapses the build
#: proceeds regardless of what is in flight — against the seconds of CPU a led
#: build was measured to steal from a turn it overlapped (§2.5:
#: ``build_ms=3979`` inside the 4a80f05e turn; Stage 2a item 7: 1,796/2,343 ms
#: turns overlapping a readiness walk against 453 ms for a non-overlapping one).
#:
#: WHY 3,500 AND NOT 1,000 (chat-turn-prep Stage 7, CP-3). Stage 5 chose one
#: second for a window that opened at ``ProfileAgentRunner.run()``. Stage 7
#: makes this wait cover the span from the handler's ANCHOR instead — the
#: pre-admit assembly ``_ACTIVE_RUNS`` cannot see — and that span was measured
#: on this PC 2026-09-07 (``planned/chat-turn-prep-cost.md`` §0.1): 3,172 /
#: 2,796 / 906 ms, a p95 of 3,172. CP-3's rule is that the bound is the measured
#: pre-admit p95 rather than a round number, because a ceiling shorter than the
#: span it now protects releases the build back into the middle of the very turn
#: it stood aside for. The cost is stated and accepted: the HUD is up to 3.5 s
#: staler while a turn is admitted, and the operator is looking at the chat.
SNAPSHOT_DEMOTE_DEFERRAL_MAX_MS = 3500

#: Poll granularity while deferring. Small enough that the common case — a turn
#: that ends mid-wait — resumes promptly, large enough not to spin.
_SNAPSHOT_DEMOTE_DEFERRAL_POLL_SECONDS = 0.025


#: The envelope type that carries ONE batch in TWO shapes at once — the promoted
#: patch and the demoted core — so a shared producer can serve a room whose
#: subscribers declared different fold sets without demoting all of them to the
#: narrowest.
#:
#: **This type never reaches a wire.** It is an INTERNAL fan-out shape: the hub
#: resolves it per subscriber (:func:`resolve_fold_variant`) and the sink is
#: handed one of the two ordinary frames inside it. A consumer that has not been
#: taught about it is resolved to the CORE — the safe half, which every client
#: since v1 folds — so no path can leak an envelope to a socket, and adding a
#: subscriber lane later cannot accidentally opt into a shape it does not
#: understand.
FOLD_VARIANTS_FRAME_TYPE = "fold_variants"

#: Upper bound on events carried by one batched delta frame. Bounds both the
#: frame's `events` list and the drain's in-memory buffer; a longer backlog
#: emits multiple batch frames, each with its own (single) core.
_DELTA_BATCH_CAP = 256


_SNAPSHOT_CANCEL_POLL_SECONDS = 0.1


def _mask_env_assignment(text: str) -> str:
    return _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)


def _redaction_safe_json(value: Any) -> Any:
    """A frame payload as JSON with env-style secret assignments masked: the walk
    is ``redaction.scrub_tree`` (lists and tuples capped at 200), every non-string
    leaf goes through ``serde.to_jsonable``."""

    return scrub_tree(value, scrub=_mask_env_assignment, list_cap=200, leaf=to_jsonable)


def first_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        text = optional_text(payload.get(key))
        if text:
            return text
    return None


#: The wire words a frame's ``type`` carries — the ones the launcher's
#: ``mission_control_bridge.dart`` scans for — spelled once. Plain constants, not
#: an Enum: ``serve/`` compares these words too, and an Enum would make them a
#: fork-wide vocabulary for W0-G5's arm (c). ``FOLD_VARIANTS_FRAME_TYPE`` above is
#: the internal envelope's word and never reaches a wire.
FRAME_HYDRATE = "hydrate"
FRAME_HEARTBEAT = "heartbeat"
FRAME_DELTA = "delta"
FRAME_PATCH = "patch"
#: The two EventLog types this package reads or writes by name: the watchdog's
#: synthetic reconcile and the run-progress trace.
EVENT_STATE_RECONCILED = "state.reconciled"
EVENT_RUN_PROGRESS = "run.progress"
