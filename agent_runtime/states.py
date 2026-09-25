from enum import StrEnum
from typing import Final


class TaskState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str) and value in _LEGACY_RUNNING_TASK_STATE_VALUES:
            return cls.RUNNING
        return None


class RunState(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_ON_TOOL = "waiting_on_tool"
    WAITING_ON_APPROVAL = "waiting_on_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"
    CANCELLED = "cancelled"


class WorkerSessionState(StrEnum):
    IDLE = "idle"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING_ON_TOOL = "waiting_on_tool"
    WAITING_ON_PROOF = "waiting_on_proof"
    SELF_HEALING = "self_healing"
    WAITING_ON_HUMAN = "waiting_on_human"
    POSSESSED = "possessed"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CLOSED = "closed"



#: The worker states in which a persona instance is an ACTIVE lane: the status
#: and snapshot rosters list it as a working agent
#: (``persona_assignments.summary.active_persona_instance_agent_summaries``),
#: whatever work pointers it does or does not carry. The one reader tests
#: membership; nothing compares a state to these words by hand.
ACTIVE_LANE_STATES: Final[frozenset[WorkerSessionState]] = frozenset(
    {
        WorkerSessionState.ASSIGNED,
        WorkerSessionState.RUNNING,
        WorkerSessionState.WAITING_ON_TOOL,
        WorkerSessionState.WAITING_ON_PROOF,
        WorkerSessionState.SELF_HEALING,
        WorkerSessionState.WAITING_ON_HUMAN,
        WorkerSessionState.POSSESSED,
    }
)

#: Persona-ASSIGNMENT states — a vocabulary of their own rather than worker
#: states (``queued`` and ``needs_input`` are assignment words): the states an
#: assignment still counts as open in, and the ones that close it.
ACTIVE_ASSIGNMENT_STATES = frozenset({"queued", "assigned", "running", "waiting_on_tool", "waiting_on_proof", "needs_input"})
TERMINAL_ASSIGNMENT_STATES = frozenset({"completed", "blocked", "cancelled"})

_LEGACY_RUNNING_TASK_STATE_VALUES = frozenset(
    {
        "pm_triage",
        "pm_ready_for_dev",
        "dev_audit",
        "dev_stage_planning",
        "dev_test_design",
        "qa_review_plan",
        "dev_implementing",
        "dev_ready_for_qa",
        "qa_testing",
        "qa_needs_fixes",
        "qa_approved",
        "pm_proof_review",
        "pm_ready_for_integration",
        "integrating",
    }
)
