"""Validate replies against the native question, before releasing its waiter."""
from __future__ import annotations

import json

from .model import ConversationError, Refusal

__layer__ = "policy"
SUPPORTED = frozenset({"approval", "clarify", "sudo", "secret", "vault.unlock_prompt", "vault.code"})


def validate_answer(request: dict, result: dict) -> None:
    from tui_gateway.contracts import SERVER_REQUESTS

    contract = SERVER_REQUESTS.get(request["method"])
    if contract is None or len(json.dumps(result, ensure_ascii=True)) > 64 * 1024:
        raise ConversationError(Refusal.INVALID_REQUEST)
    try:
        contract.result.model_validate(result)
    except ValueError as exc:
        raise ConversationError(Refusal.INVALID_REQUEST) from exc
    params = request["params"]
    if request["method"] == "approval" and result.get("choice") not in params.get("choices", ()):
        raise ConversationError(Refusal.INVALID_REQUEST)
    if request["method"] == "clarify" and "answers" in result:
        allowed = {row["qid"] for row in params.get("questions") or ()}
        if not set(result.get("answers") or {}).issubset(allowed):
            raise ConversationError(Refusal.INVALID_REQUEST)
