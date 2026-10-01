"""Profile admission, native execution and budget failures."""

from __future__ import annotations

from typing import Any

__layer__ = "models"

__all__ = ["ProfileRunnerError", "RunBudgetExceeded", "_NO_WALL_BUDGET_SECONDS"]


class ProfileRunnerError(RuntimeError):
    """An execution failure with optional native provider evidence."""

    def __init__(self, message: str, *, provider_error: dict[str, Any] | None = None):
        super().__init__(message)
        self.provider_error = provider_error


class RunBudgetExceeded(ProfileRunnerError):
    """A confirmed budget exhaustion, distinct from an uncertain execution."""

    def __init__(
        self,
        message: str,
        *,
        session_id: str | None = None,
        wall_budget: dict[str, Any] | None = None,
        run_budget: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.session_id = session_id
        self.wall_budget = wall_budget
        self.run_budget = run_budget


# Unbounded runs keep the same checkpoint shape without arming a timer.
_NO_WALL_BUDGET_SECONDS = 3650.0 * 24 * 3600
