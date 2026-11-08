"""What a Launcher app-function answer means to the model (Stage 7, harness half).

The Launcher's dispatcher answers a call with ``{"data": …}`` or with a JSON-RPC
error whose ``data.refusal`` is one of its typed refusals
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
    "LAUNCHER_REFUSALS",
    "RETRY_AFTER_CHANGE",
    "RETRY_LATER",
    "RETRY_NEVER",
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


#: Eternia's own vocabulary, by its wire name (eternia
#: `lib/core/app_functions/app_function_outcome.dart`, `AppFunctionRefusal`).
LAUNCHER_REFUSALS: Mapping[str, RefusalMeaning] = {
    "unknown_function": RefusalMeaning(
        RETRY_NEVER, "Eternia has no such app function; it may have been removed since it was listed"),
    # Not "did not validate against the schema": Eternia answers this code
    # for any argument it cannot use, a JSON syntax error inside one string
    # argument included, and the message names what to change.
    "invalid_arguments": RefusalMeaning(
        RETRY_AFTER_CHANGE, "Eternia rejected these arguments; its message says what to change before calling again"),
    "refused_by_policy": RefusalMeaning(
        RETRY_NEVER, "Eternia's policy refuses this function to agents"),
    "not_reachable_from_caller": RefusalMeaning(
        RETRY_NEVER, "this function runs only from Eternia's own machine; this turn's origin cannot reach it"),
    "opt_in_off": RefusalMeaning(
        RETRY_NEVER, "the person has not switched this set of functions on in Eternia"),
    "confirmation_declined": RefusalMeaning(
        RETRY_NEVER, "the person declined the approval card in Eternia; do not call again unless they ask"),
    "unavailable": RefusalMeaning(
        RETRY_LATER, "Eternia could not reach what this function needs right now"),
    "failed": RefusalMeaning(
        RETRY_LATER, "the function ran and failed; inspect the message before retrying"),
    # -32007: the generated panel's script scope that made the call is no
    # longer current (the panel closed or was replaced); that scope can never
    # call again.
    "script_scope_expired": RefusalMeaning(
        RETRY_NEVER, "the Eternia panel that made this call is closed or was replaced; its calls cannot run any more"),
    # -32008: the panel's document never declared this operation, or the
    # account does not grant it (a revoked capability, not a script bug).
    "script_operation_denied": RefusalMeaning(
        RETRY_NEVER, "this panel is not allowed this operation in Eternia; do not call it again from here"),
    # -32009: the function's audience does not admit this turn's origin.
    "not_for_outside_agents": RefusalMeaning(
        RETRY_NEVER, "Eternia keeps this function for its own agents; an agent from outside cannot call it"),
    # -32010 (edge note E8): the same call, same arguments, is already running
    # at its door; the repeat was not a second run.
    "in_flight": RefusalMeaning(
        RETRY_LATER, "the same call is already running in Eternia; wait for it to finish instead of calling again"),
    # -32011 (edge note E14): the signed-in account changed between the
    # call's start and its door; a call queued under one account never runs
    # as another.
    "account_changed": RefusalMeaning(
        RETRY_LATER, "the account signed in to Eternia changed before this call ran; check who is signed in before calling again"),
    # A native control whose press does not end at a checked door yet (eternia
    # `AppFunctionRefusal.unmigrated`, -32012; ruling
    # OR-2026-11-06-native-controls-press-by-tag): pressing it again can never
    # run it, but the function its controls-list line names can.
    "unmigrated": RefusalMeaning(
        RETRY_NEVER,
        "this control cannot be pressed by an agent yet; do not press it again — call the app function"
        " its launcher.ui.controls.list line names instead, or ask the person to press it"),
}

#: What this runtime answers on its own, when no Eternia answer exists.
RUNTIME_REFUSALS: Mapping[str, RefusalMeaning] = {
    "no_launcher": RefusalMeaning(
        RETRY_NEVER, "Eternia is not attached to this turn; app functions are unavailable"),
    "connection_closed": RefusalMeaning(
        RETRY_NEVER, "the Eternia connection closed before it answered; the request was not resent"),
    "no_reply": RefusalMeaning(
        RETRY_LATER, "Eternia did not answer in time"),
}

_UNKNOWN = RefusalMeaning(RETRY_LATER, "Eternia refused with a reason this runtime does not know")
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
