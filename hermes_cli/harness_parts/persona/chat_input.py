"""Translate CLI arguments into the runtime's validated chat input."""
from __future__ import annotations

import json

from agent_runtime.operator_input import OperatorInput, operator_input
from agent_runtime.reviewed_prompt import ReviewedPromptError

__layer__ = "lanes"


def input_from_args(args) -> OperatorInput:
    raw = getattr(args, "reviewed_prompt_json", None)
    try:
        prompt = json.loads(raw) if raw is not None else None
    except (ValueError, TypeError) as exc:
        raise ReviewedPromptError("invalid_prompt") from exc
    return operator_input(getattr(args, "message", None), prompt)
