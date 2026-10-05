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

# ── source (§1): three, failing independently ───────────────────────────────
SOURCE_AGENT = "agent"
SOURCE_ANNOUNCED = "announced"
SOURCE_DETECTED = "detected"
BUILD_SOURCES = (SOURCE_AGENT, SOURCE_ANNOUNCED, SOURCE_DETECTED)

# ── what ``work peek`` read for a build row (``tail_source``) ───────────────
TAIL_SOURCE_TERMINAL = "terminal_buffer"
TAIL_SOURCE_BUILD_LOG = "build_log"
TAIL_SOURCE_RECORD = "record_tail"
BUILD_TAIL_SOURCES = (TAIL_SOURCE_TERMINAL, TAIL_SOURCE_BUILD_LOG, TAIL_SOURCE_RECORD)

# ── liveness and outcome (§1) ───────────────────────────────────────────────
LIVENESS_LIVE = "live"
LIVENESS_STALLED = "stalled"
LIVENESS_DEAD = "dead"
LIVENESS_UNKNOWN = "unknown"
BUILD_LIVENESS = (LIVENESS_LIVE, LIVENESS_STALLED, LIVENESS_DEAD, LIVENESS_UNKNOWN)

OUTCOME_SUCCEEDED = "succeeded"
OUTCOME_FAILED = "failed"
OUTCOME_STALLED = "stalled"
OUTCOME_STOPPED = "stopped"
OUTCOME_LOST = "lost"
#: ``null`` (still running) is the sixth arm and is not a word.
BUILD_OUTCOMES = (OUTCOME_SUCCEEDED, OUTCOME_FAILED, OUTCOME_STALLED, OUTCOME_STOPPED, OUTCOME_LOST)

PROGRESS_SIGNAL_OUTPUT = "output"
PROGRESS_SIGNAL_HEARTBEAT = "heartbeat"
PROGRESS_SIGNAL_CPU = "cpu"
PROGRESS_SIGNAL_NONE = "none"
PROGRESS_SIGNALS = (PROGRESS_SIGNAL_OUTPUT, PROGRESS_SIGNAL_HEARTBEAT, PROGRESS_SIGNAL_CPU, PROGRESS_SIGNAL_NONE)

# ── toolchain, mode, started_by (§1) ─────────────────────────────────────────
TOOLCHAIN_FLUTTER = "flutter"
TOOLCHAIN_DART = "dart"
TOOLCHAIN_UNKNOWN = "unknown"
BUILD_TOOLCHAINS = (TOOLCHAIN_FLUTTER, TOOLCHAIN_DART, TOOLCHAIN_UNKNOWN)
#: Reserved words, NOT emitted yet — a consumer may pre-render them, no producer writes one.
RESERVED_TOOLCHAINS = ("gradle", "msbuild", "cmake", "npm", "cargo", "unreal")

BUILD_MODES = ("debug", "profile", "release", "")

STARTED_BY_AGENT = "agent"
STARTED_BY_OPERATOR = "operator"
STARTED_BY_TOOL = "tool"
STARTED_BY_EXTERNAL = "external"
STARTED_BY_KINDS = (STARTED_BY_AGENT, STARTED_BY_OPERATOR, STARTED_BY_TOOL, STARTED_BY_EXTERNAL)

# ── env_source (§1): what environment the build ran (or will restart) with ──
ENV_SOURCE_SLOT_PREFIX = "slot:"
ENV_SOURCE_PROCESS = "process"
ENV_SOURCE_UNKNOWN = "unknown"
#: ``slot:<name>`` is an arm with a parameter; the tuple names the arm by its prefix.
ENV_SOURCE_ARMS = (ENV_SOURCE_SLOT_PREFIX, ENV_SOURCE_PROCESS, ENV_SOURCE_UNKNOWN)

# ── controls (§1, §7) ────────────────────────────────────────────────────────
CONTROL_ALLOWED = "allowed"
CONTROL_REFUSED = "refused"
CONTROL_UNAVAILABLE = "unavailable"
CONTROL_STATES = (CONTROL_ALLOWED, CONTROL_REFUSED, CONTROL_UNAVAILABLE)

CONTROL_REASON_NOT_RUNNING = "not_running"
CONTROL_REASON_OWNER_NOT_HERE = "owner_not_here"
CONTROL_REASON_WRITER_DECLINES = "writer_declines"
CONTROL_REASON_ARGV_UNKNOWN = "argv_unknown"
CONTROL_REASON_SLOT_UNBOUND = "slot_unbound"
CONTROL_REASONS = (
    CONTROL_REASON_NOT_RUNNING,
    CONTROL_REASON_OWNER_NOT_HERE,
    CONTROL_REASON_WRITER_DECLINES,
    CONTROL_REASON_ARGV_UNKNOWN,
    CONTROL_REASON_SLOT_UNBOUND,
)

# ── the announced-job registry (§2) ───────────────────────────────────────────
#: ``<background-work home>/builds/`` — beside ``processes.json`` and ``mcp_jobs.json``.
BUILD_REGISTRY_DIRNAME = "builds"
REGISTRY_SCHEMA_VERSION = 1
#: Exported into serve's own ``os.environ`` at boot so every child it spawns can announce.
REGISTRY_DIR_ENV = "HERMES_BUILD_REGISTRY_DIR"
#: The writer's own ``status`` words.
RECORD_STATUS_QUEUED = "queued"
RECORD_STATUS_RUNNING = "running"
RECORD_STATUS_FINISHED = "finished"
RECORD_STATUSES = (RECORD_STATUS_QUEUED, RECORD_STATUS_RUNNING, RECORD_STATUS_FINISHED)
#: ``controls.stop`` / ``controls.restart`` as a WRITER declares them.
RECORD_STOP_REQUEST = "request"
RECORD_STOP_KILL_TREE = "kill_tree"
RECORD_CONTROL_NONE = "none"
RECORD_STOP_MODES = (RECORD_STOP_REQUEST, RECORD_STOP_KILL_TREE, RECORD_CONTROL_NONE)
RECORD_RESTART_COMMAND = "command"
RECORD_RESTART_MODES = (RECORD_RESTART_COMMAND, RECORD_CONTROL_NONE)
#: The stop request a ``request``-mode writer watches for, beside its record.
STOP_REQUEST_SUFFIX = ".stop"

#: Seconds without a heartbeat (announced) or progress (agent, detected) before ``stalled``.
DEFAULT_STALL_SECONDS = 240.0
#: Seconds ``stalled`` before an agent/announced build is ENDED (§7); detected builds are only marked.
DEFAULT_STALL_FAIL_SECONDS = 900.0
#: A running record's ``expires_at`` = start + 6 h (the wake's ``_ROUTE_TTL_S``).
RUNNING_RECORD_TTL_SECONDS = 6 * 60 * 60
#: A finished record's ``expires_at`` = finish + 30 min (the wake's ``_FINISHED_TTL_S``).
FINISHED_RECORD_TTL_SECONDS = 30 * 60
#: The serve-boot sweep deletes record files this long past their ``expires_at`` (§2).
RECORD_GC_GRACE_SECONDS = 24 * 60 * 60

# ── sub-health reasons on ``sources.build.sub.*`` (§1) ───────────────────────
SUB_REASON_NOT_IN_PROCESS = "not_in_process"
SUB_REASON_NO_SLOTS_DECLARED = "no_slots_declared"
SUB_REASON_SLOTS_UNBOUND_HERE = "slots_unbound_here"
SUB_REASON_SCAN_BUDGET = "scan_budget"
SUB_REASON_SCAN_FAILED = "scan_failed"
SUB_REASON_REGISTRY_UNREADABLE = "registry_unreadable"
DETECTED_SUB_REASONS = (
    SUB_REASON_NOT_IN_PROCESS,
    SUB_REASON_NO_SLOTS_DECLARED,
    SUB_REASON_SLOTS_UNBOUND_HERE,
    SUB_REASON_SCAN_BUDGET,
    SUB_REASON_SCAN_FAILED,
)
ANNOUNCED_SUB_REASONS = (SUB_REASON_REGISTRY_UNREADABLE,)

#: Bounds on row text (§1).
COMMAND_LIMIT = 400
LABEL_LIMIT = 120

#: The detected source's ONE bound (§5, owner call 7): a scan over this many ms is
#: ``detected: unavailable scan_budget`` with the measured ``scan_ms`` still reported.
DETECT_BUDGET_MS = 50
