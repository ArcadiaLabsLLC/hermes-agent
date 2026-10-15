"""Non-blocking ``clarify`` bridge for the Mission Control operator/relay lane.

The CLI/gateway ``clarify`` callback blocks on a human input queue (see
``hermes_cli/callbacks.clarify_callback``). A one-shot Mission Control chat turn
has no such interactive queue to block on — it is spawned, runs, and returns a
reply. So on this lane ``clarify`` must not block: calling it RECORDS the
structured question and returns a sentinel that tells the model to end its turn
with the question as its reply.

The mission-chat handler reads the recorded :class:`MissionChatClarifyCapture`
after the run and threads it back to whoever asked — the operator (rendered as
pickable options in the HUD) or the parent agent that briefed this one via
``agent_chat_send``. The answer arrives as the next message in the SAME session,
so a clarification is an ordinary conversational turn, never a typed failure.

This is the seam that lets a child surface context only it has ("which dev —
launcher or backend?") instead of the parent guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

__layer__ = "models"

# Mirror tools.clarify_tool.MAX_CHOICES: the UI appends its own "Other" row.
MAX_CHOICES = 4

#: ``outcome`` this lane reports back to ``tools.clarify_tool``: the questions
#: were handed to the asker, and the wait ends with the TURN, not with an answer.
OUTCOME_ROUTED = "routed"


@dataclass(slots=True)
class MissionChatClarifyCapture:
    """Records the first ``clarify`` call of a mission-chat turn.

    ``callback`` speaks upstream's batched contract (``tools.clarify_tool``):
    it receives the NORMALIZED question list (each entry carries ``qid``,
    ``question``, ``choices_offered``, ``multi_select``) and returns
    ``{"answers", "outcome", "notice"}``. No answer exists yet, so ``answers``
    is empty and ``notice`` tells the model to end its turn with the questions.

    First call wins: the model is told to stop after asking, so a second call
    should not happen — but if it does, the questions we already reported to
    the caller stay authoritative rather than being overwritten mid-turn.
    """

    questions: list[dict[str, object]] | None = None

    @property
    def requested(self) -> bool:
        return bool(self.questions)

    @property
    def question(self) -> str | None:
        """The prompt text the launcher's choice card shows."""
        if not self.questions:
            return None
        if len(self.questions) == 1:
            return str(self.questions[0]["question"])
        return "\n".join(
            f"{index}. {entry['question']}"
            for index, entry in enumerate(self.questions, 1)
        )

    @property
    def choices(self) -> list[str] | None:
        """Pickable options — only for a single question (one pick answers it)."""
        if not self.questions or len(self.questions) != 1:
            return None
        return list(self.questions[0].get("choices") or []) or None

    @property
    def request(self) -> dict[str, object] | None:
        """Structured payload threaded back to the caller, or None.

        ``question`` / ``choices`` are the frame the launcher's choice prompt
        reads. Several questions fold into one numbered ``question`` with no
        top-level ``choices`` (a single pick cannot answer them all), and the
        per-question structure rides beside it in ``questions``."""
        if not self.requested:
            return None
        payload: dict[str, object] = {"question": self.question}
        if self.choices:
            payload["choices"] = list(self.choices)
        if len(self.questions or []) == 1 and self.questions[0].get("multi_select"):
            payload["multi_select"] = True
        if len(self.questions or []) > 1:
            payload["questions"] = [dict(entry) for entry in self.questions or []]
        return payload

    def callback(self, questions: list[dict[str, object]]) -> dict[str, object]:
        if self.questions is None:
            recorded = [
                _entry(item) for item in (questions or []) if isinstance(item, dict)
            ]
            recorded = [entry for entry in recorded if entry["question"]]
            self.questions = recorded or None
        if not self.requested:
            return {
                "answers": {},
                "outcome": OUTCOME_ROUTED,
                "notice": "clarify requires a non-empty question — nothing was recorded.",
            }
        return {"answers": {}, "outcome": OUTCOME_ROUTED, "notice": self._sentinel()}

    def _sentinel(self) -> str:
        options_hint = ""
        if self.choices:
            options_hint = (
                " You offered these options, so they can pick one: "
                + "; ".join(self.choices)
                + "."
            )
        plural = len(self.questions or []) > 1
        noun = "questions" if plural else "question"
        return (
            f"Your clarifying {noun} {'were' if plural else 'was'} routed to whoever "
            "asked you — the operator, or the agent that briefed you — and their "
            "answer will arrive as the next message in this same conversation. End "
            f"your turn now with the {noun} as your reply, phrased in your own "
            "natural voice." + options_hint + " Do not act or guess until they answer."
        )


def _entry(item: dict[str, object]) -> dict[str, object]:
    """One normalized upstream question, reduced to what the caller is shown.

    ``choices_offered`` is the BARE list (upstream decorates ``choices`` with a
    "(Recommended)" label that is presentation, not an option)."""
    offered = item.get("choices_offered")
    if offered is None:
        offered = item.get("choices")
    cleaned = [
        choice.strip()
        for choice in (offered if isinstance(offered, list) else [])
        if isinstance(choice, str) and choice.strip()
    ][:MAX_CHOICES]
    entry: dict[str, object] = {"question": str(item.get("question") or "").strip()}
    if cleaned:
        entry["choices"] = cleaned
    if item.get("multi_select") and cleaned:
        entry["multi_select"] = True
    return entry
