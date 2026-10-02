"""What a Launcher app-function answer means to the model (Stage 7, harness half).

The Launcher's dispatcher answers a call with ``{"data": …}`` or with a JSON-RPC
error whose ``data.refusal`` is one of eight typed refusals
(``EterniaLauncher/lib/features/mission_control/data/app_functions/
app_function_dispatcher.dart``, ``AppFunctionRefusal``); the runtime adds three
of its own for a Launcher that is absent, gone or silent. This module is the
ONE reading of those words: each refusal maps to whether a retry can ever
help and to a sentence the model can act on, and a ``confirm`` entry's success
is marked as the person's approval. Pure: a table and two builders, no wire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

__layer__ = "policy"

__all__ = [
    "RETRY_AFTER_CHANGE",
    "RETRY_LATER",
    "RETRY_NEVER",
    "LAUNCHER_REFUSALS",
    "RUNTIME_REFUSALS",
    "RefusalMeaning",
    "refusal_result",
    "success_result",
]

#: The same call again cannot succeed; only the person (or the Launcher's
#: policy) can change the answer.
RETRY_NEVER = "never"
#: The call can succeed once its ARGUMENTS change.
RETRY_AFTER_CHANGE = "after_change"
#: The call may succeed later, unchanged; inspect before retrying.
RETRY_LATER = "later"


@dataclass(frozen=True, slots=True)
class RefusalMeaning:
    """One refusal word, read for the model."""

    retry: str
    detail: str


#: The Launcher's own vocabulary, by its wire name.
LAUNCHER_REFUSALS: Mapping[str, RefusalMeaning] = {
    "unknown_function": RefusalMeaning(
        RETRY_NEVER, "the Launcher has no such app function; it may have been removed since it was listed"),
    "invalid_arguments": RefusalMeaning(
        RETRY_AFTER_CHANGE, "the arguments did not validate against the function's schema; fix them before calling again"),
    "refused_by_policy": RefusalMeaning(
        RETRY_NEVER, "the Launcher's policy refuses this function to agents"),
    "not_reachable_from_caller": RefusalMeaning(
        RETRY_NEVER, "this function runs only from the Launcher's own machine; this turn's origin cannot reach it"),
    "opt_in_off": RefusalMeaning(
        RETRY_NEVER, "the person has not switched this set of functions on in the Launcher"),
    "confirmation_declined": RefusalMeaning(
        RETRY_NEVER, "the person declined the approval card at the Launcher; do not call again unless they ask"),
    "unavailable": RefusalMeaning(
        RETRY_LATER, "the Launcher could not reach what this function needs right now"),
    "failed": RefusalMeaning(
        RETRY_LATER, "the function ran and failed; inspect the message before retrying"),
}

#: What this runtime answers on its own, when no Launcher answer exists.
RUNTIME_REFUSALS: Mapping[str, RefusalMeaning] = {
    "no_launcher": RefusalMeaning(
        RETRY_NEVER, "no Launcher is attached to this turn; app functions are unavailable"),
    "connection_closed": RefusalMeaning(
        RETRY_NEVER, "the Launcher connection closed before it answered; the request was not resent"),
    "no_reply": RefusalMeaning(
        RETRY_LATER, "the Launcher did not answer in time"),
}

_UNKNOWN = RefusalMeaning(RETRY_LATER, "the Launcher refused with a reason this runtime does not know")
#: The Launcher's word for the person saying no at the approval card.
_CONFIRMATION_DECLINED = "confirmation_declined"


def success_result(result: Mapping[str, Any], *, requires_confirmation: bool) -> dict[str, Any]:
    """The Launcher's result as the tool result. A ``confirm`` entry's success
    means the person approved it at the Launcher, and the model is told so."""

    answer = dict(result)
    if requires_confirmation:
        answer["confirmed"] = True
    return answer


def refusal_result(*, refusal: Any, code: int, message: str, requires_confirmation: bool) -> dict[str, Any]:
    """A refusal as the tool result: the Launcher's word, the code and message
    it sent, and this module's reading of it (``retry``, ``detail``)."""

    name = refusal if isinstance(refusal, str) else None
    meaning = LAUNCHER_REFUSALS.get(name) or RUNTIME_REFUSALS.get(name) or _UNKNOWN
    answer = {"error": message, "code": code, "refusal": name,
              "retry": meaning.retry, "detail": meaning.detail}
    if requires_confirmation and name == _CONFIRMATION_DECLINED:
        answer["confirmed"] = False
    return answer
