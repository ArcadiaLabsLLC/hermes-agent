"""The stream lane: v1 full-core and v2 patch frames for ``hermes harness stream``
and the serve hub (owner doc ``docs/agent-runtime-harness/03-transport-and-wire.md``).

The single file had no module docstring; its design lived in the ``#:``
comments on its constants (now ``vocabulary``) and in the phase comments inside
``stream_frames`` (now ``session``). This map is written from them.

The package map (program rule 16; layout sheet ``stream.md`` §1)
----------------------------------------------------------------

Modules, lowest layer first; no module imports one above it (W0-G6)::

    agent_runtime/stream/
      __init__.py      lanes   this map; re-exports the importers' names and the tests' names
      vocabulary.py    models  STREAM_SCHEMA_VERSION / _PATCH_, DEFAULT_STREAM_CALLER,
                               BATCH_REASON_DEMOTE, the deferral bound + poll,
                               FOLD_VARIANTS_FRAME_TYPE, _DELTA_BATCH_CAP, the cancel poll,
                               FRAME_* / EVENT_* (the wire and log words, spelled once),
                               the package logger, _redaction_safe_json (over
                               redaction.scrub_tree), first_text
                               (a vocabulary module: exempt from the floor)
      build_policy.py  stores  what a core build records and when it stands aside: the
                               Stage 5/7 deferral, _log_snapshot_build, log_stream_attach /
                               log_stream_denied
      frames.py        lanes   one frame each: hydrate, heartbeat, delta, delta batch,
                               patch batch, fold variants (+ resolve_fold_variant); the
                               watchdog append, _delta_op, _identity_map
      build.py         lanes   one core build with liveness: _is_one_shot,
                               _SnapshotBuildJob, _build_with_liveness, the batch frames
      fingerprint.py   stores  _scope_fingerprint: the watchdog's stat of event-less state,
                               by store family (pointers + catalogs, chat DB, running_work)
      session.py       lanes   stream_frames -> StreamSession (stale_first -> boot ->
                               tail; a pass = measure -> fingerprint -> room -> drain ->
                               settle -> flush -> beat)

    entry point                                        opens
    stream_frames (serve subscriptions, harness stream) session -> build -> frames
                                                        (+ fingerprint, one call a pass)
    _build_with_liveness / _batch_frames_with_liveness  build -> frames -> build_policy
    the frame builders (fixture generator, stream_resume) frames
    log_stream_attach / log_stream_denied (serve)       build_policy
    resolve_fold_variant (serve_stream_hub)             frames

No module here names a package MAP: ``core_cache.lane`` / ``.shadow`` /
``.walk``, ``profile_runner.workdir``, ``snapshot.build`` / ``.receipts`` and
``state_patches.models`` / ``.emit`` are read at their defining modules, which is
what keeps the package at ``lanes``. ``frames`` is ``lanes`` because
``hydrate_frame`` builds the snapshot itself.
"""

from __future__ import annotations

# Names the single file bound by import and tests read (or wrap) off it;
# a STUB goes where the name is bound (tests/_downstream/split_package_source.py
# ::patch_where_bound), never on this package attribute alone.
from ..parity import core_event_offset
from ..request_control import request_cancelled
from ..snapshot.build import build_snapshot
from ..state_patches.emit import delta_patches_enabled

from . import build, build_policy, fingerprint, frames, session, vocabulary
from .build import (
    _SnapshotBuildJob,
    _batch_frames_with_liveness,
    _build_with_liveness,
    _full_core_batch_frames,
)
from .build_policy import (
    _agent_runs_in_flight,
    _chat_turns_admitted,
    _defer_demote_build_for_active_turns,
    _log_snapshot_build,
    log_stream_attach,
    log_stream_denied,
)
from .fingerprint import (
    _scope_fingerprint,
)
from .frames import (
    _delta_op,
    _identity_map,
    batch_carries_patch_rows,
    delta_batch_frame,
    delta_frame,
    fold_variants_frame,
    heartbeat_frame,
    hydrate_frame,
    patch_batch_frame,
    resolve_fold_variant,
)
from .session import (
    StreamSession,
    stream_frames,
)
from .vocabulary import (
    BATCH_REASON_DEMOTE,
    DEFAULT_STREAM_CALLER,
    EVENT_RUN_PROGRESS,
    EVENT_STATE_RECONCILED,
    FOLD_VARIANTS_FRAME_TYPE,
    FRAME_DELTA,
    FRAME_HEARTBEAT,
    FRAME_HYDRATE,
    FRAME_PATCH,
    SNAPSHOT_DEMOTE_DEFERRAL_MAX_MS,
    STREAM_PATCH_SCHEMA_VERSION,
    STREAM_SCHEMA_VERSION,
    _DELTA_BATCH_CAP,
    first_text,
    logger,
)

__layer__ = "lanes"

