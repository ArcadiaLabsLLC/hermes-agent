"""The build vocabulary: the wire enums a ``build`` row carries, one tuple each, and the limits.

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §1 (the
``build`` row) and §2 (the announced-job registry). A vocabulary module: every word a
consumer branches on is declared HERE once, and the golden fixture
(``tests/fixtures/builds/build_rows.json``) is checked against these tuples rather than a
literal typed beside it.
"""

from __future__ import annotations

__layer__ = "models"

# ── stage (§1, §4): monotonic, forward only ───────────────────────────────────
STAGE_QUEUED = "queued"
STAGE_PREPARING = "preparing"
STAGE_RESOLVING = "resolving"
STAGE_COMPILING = "compiling"
STAGE_LINKING = "linking"
STAGE_PACKAGING = "packaging"
STAGE_FINISHING = "finishing"
STAGE_DONE = "done"
STAGE_UNKNOWN = "unknown"

#: In forward order; ``unknown`` last because it is never advanced TO, only started from.
BUILD_STAGES = (
    STAGE_QUEUED,
    STAGE_PREPARING,
    STAGE_RESOLVING,
    STAGE_COMPILING,
    STAGE_LINKING,
    STAGE_PACKAGING,
    STAGE_FINISHING,
    STAGE_DONE,
    STAGE_UNKNOWN,
)

#: ``stage_detail`` bound, in characters (the last matched line, redacted).
STAGE_DETAIL_LIMIT = 120

# ── artifact kind (§1) ───────────────────────────────────────────────────────
ARTIFACT_KIND_EXECUTABLE = "executable"
ARTIFACT_KIND_BUNDLE = "bundle"
ARTIFACT_KIND_DIRECTORY = "directory"
ARTIFACT_KIND_OTHER = "other"

ARTIFACT_KINDS = (ARTIFACT_KIND_EXECUTABLE, ARTIFACT_KIND_BUNDLE, ARTIFACT_KIND_DIRECTORY, ARTIFACT_KIND_OTHER)
