"""The stream lane: v1 full-core and v2 patch frames for ``hermes harness stream``
and the serve hub (owner doc ``docs/agent-runtime-harness/03-transport-and-wire.md``).

The single file had no module docstring; its design lived in the ``#:``
comments on its constants (now ``vocabulary``) and in the phase comments inside
``stream_frames`` (now ``session``). This map is written from them.

The package map (program rule 16; layout sheet ``stream.md`` §1)
----------------------------------------------------------------

Modules, lowest layer first; no module imports one above it (W0-G6)::

    agent_runtime/stream/
      __init__.py      wiring  this map; re-exports the importers' names and the tests' names
      vocabulary.py    models  STREAM_SCHEMA_VERSION / _PATCH_, DEFAULT_STREAM_CALLER,
                               BATCH_REASON_DEMOTE, the deferral bound + poll,
                               FOLD_VARIANTS_FRAME_TYPE, _DELTA_BATCH_CAP, the cancel poll,
                               the package logger, _redaction_safe_json, _first_text
                               (a vocabulary module: exempt from the floor)
      build_policy.py  wiring  what a core build records and when it stands aside: the
                               Stage 5/7 deferral, _log_snapshot_build, log_stream_attach /
                               log_stream_denied
      frames.py        wiring  one frame each: hydrate, heartbeat, delta, delta batch,
                               patch batch, fold variants (+ resolve_fold_variant); the
                               watchdog append, _delta_op, _identity_map
      build.py         wiring  one core build with liveness: _is_one_shot,
                               _SnapshotBuildJob, _build_with_liveness, the batch frames
      session.py       wiring  stream_frames (the session that owns a tail) and
                               _scope_fingerprint

    entry point                                        opens
    stream_frames (serve subscriptions, harness stream) session -> build -> frames
    _build_with_liveness / _batch_frames_with_liveness  build -> frames -> build_policy
    the frame builders (fixture generator, stream_resume) frames
    log_stream_attach / log_stream_denied (serve)       build_policy
    resolve_fold_variant (serve_stream_hub)             frames

Every module but ``vocabulary`` is ``wiring`` in this commit only because the
spans still name two package maps (``core_cache``, and ``profile_runner`` in
the deferral's lazy import); the CHANGE reads their defining modules instead.
"""

from __future__ import annotations

# Names the single file bound by import and tests read (or wrap) off it;
# a STUB goes where the name is bound (tests/_downstream/split_package_source.py
# ::patch_where_bound), never on this package attribute alone.
from ..parity import core_event_offset
from ..request_control import request_cancelled
from ..snapshot.build import build_snapshot
from ..state_patches.emit import delta_patches_enabled

from . import build, build_policy, frames, session, vocabulary
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
    _scope_fingerprint,
    stream_frames,
)
from .vocabulary import (
    BATCH_REASON_DEMOTE,
    DEFAULT_STREAM_CALLER,
    FOLD_VARIANTS_FRAME_TYPE,
    SNAPSHOT_DEMOTE_DEFERRAL_MAX_MS,
    STREAM_PATCH_SCHEMA_VERSION,
    STREAM_SCHEMA_VERSION,
    _DELTA_BATCH_CAP,
    logger,
)

__layer__ = "wiring"

