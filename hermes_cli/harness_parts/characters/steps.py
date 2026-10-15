"""The four pipeline steps (turnaround, approve-direction, rows, compose) and their one-call verbs.

Separate because both doors call these bodies: the interactive verbs one step
per call, and ``auto`` all four in one process.
"""

from __future__ import annotations

from .payloads import _attempt_label, _characters_next, _characters_verb

__layer__ = "lanes"
__all__ = [
    "_characters_face_offset_label",
    "_characters_face_offsets",
    "_characters_rows_next",
    "_characters_step_approve_all",
    "_characters_step_compose",
    "_characters_step_rows",
    "_characters_step_turnaround",
    "_cmd_characters_approve_direction",
    "_cmd_characters_compose",
    "_cmd_characters_reroll_direction",
    "_cmd_characters_reroll_row",
    "_cmd_characters_rows",
    "_cmd_characters_turnaround",
]


# ── the four pipeline steps, as callables both doors share ──────────────────
#
# `turnaround → approve-direction --all → rows → compose` is driven from two
# places now: one verb per call (the interactive lane) and `characters auto`
# (the one-shot lane, Stage 5). The plan's promise for `auto` is that each stage
# receipt is "the same payload the verb prints today" — a promise a copy of the
# body could not keep for longer than the next edit to one of them. So the body
# lives once, here, and both doors call it.


def _characters_step_turnaround(draft):
    result = draft.run_turnaround()
    directions = ", ".join(sorted(result.get("turnaround", {})))
    return result, f"Draft {draft.id}: proposed turnaround references for {directions} (awaiting approval)"


def _characters_face_offset_label(offset) -> str:
    """One approved reference's measured facing, spelled for a person.

    The sign is the reading — positive is a head to the RIGHT of frame — so it
    is always printed, and the word beside it is there because a bare `+10.9` in
    a receipt is a number an operator has to go and look up. Approving a
    turnaround said nothing about the direction until this line existed.
    """
    if offset is None:
        return "facing unmeasured (no image to read)"
    if offset > 0:
        return f"face offset +{offset:.1f} px (head right of body centre)"
    if offset < 0:
        return f"face offset {offset:.1f} px (head LEFT of body centre)"
    return "face offset 0.0 px (head over body centre)"


def _characters_face_offsets(offsets: dict) -> str:
    """The same measurement for a whole turnaround, in one clause.

    Compact on purpose: `--all` approves five references at once and the line
    has to stay one line, so it is the signed numbers in the order they were
    approved. The disagreement this exists to surface is legible as a sign
    that does not match its neighbours.
    """
    if not offsets:
        return "no facings measured"
    return "face offsets " + ", ".join(
        f"{direction} {'unmeasured' if value is None else format(value, '+.1f')}"
        for direction, value in offsets.items()
    )


def _characters_step_approve_all(draft):
    result = draft.approve_all_directions()
    human = (
        f"Draft {draft.id}: approved {len(result['approved'])} direction(s) "
        f"({_characters_face_offsets(result['faceOffsets'])}); "
        f"stage is now '{draft.stage}'"
    )
    # Only when the approval ADVANCED the stage. `rows` refuses at stage
    # `turnaround`, and the payload already says `advanced: false` — a hint
    # disagreeing with the key beside it is a payload arguing with itself.
    if result.get("advanced"):
        result["next"] = _characters_next("rows", "--draft", draft.id)
    return result, human


def _characters_step_rows(draft, only: list[str] | None):
    result = draft.run_rows(only=only)
    return result, f"Draft {draft.id}: generated {len(result.get('rows', {}))} row strip(s)"


def _characters_step_compose(draft, accept: list[str]):
    from agent.charsheet import pipeline

    result = draft.compose(accept_handedness=accept)
    validation = result["validation"]
    # The handedness accounting rides on the SUCCESS line too. A clean
    # `composed → 1536x3120` told an operator nothing about the six of
    # fifteen rows the check could not answer for, and a clean pass has never
    # been a certificate.
    #
    # The WARNINGS ride on it as well, and that is not cosmetic. A
    # single-basis handedness finding no longer blocks, and an accepted one
    # never did: both are warnings, `validation["warnings"]` needs `--json`,
    # and a successful `--accept-handedness` therefore used to print a row
    # count and nothing else — no gain, no basis, no reason. A warning
    # nobody prints is the shape of the failure this whole lane exists to
    # retire.
    lines = [
        f"Draft {draft.id} composed → {result['slug']} "
        f"({validation['width']}x{validation['height']}) at {result['sheet']}; "
        + pipeline.handedness_summary(validation["handedness"])
    ]
    # A warning is a BLOCK now, not a sentence, so its continuation lines
    # are pushed under the same indent rather than falling back to column
    # zero and reading as separate output.
    lines += [
        "  warning: " + text.replace("\n", "\n  ")
        for text in validation["warnings"]
    ]
    return result, "\n".join(lines)


def _characters_rows_next(draft, only: list[str] | None) -> dict | None:
    """A batch that died mid-flight is the expensive moment to be lost in.

    `run_rows` generates and approves row by row, so a refusal leaves some
    rows landed and the rest not — and the two moves from here are re-roll
    the row that died (a `--note` is what changes the prompt) or resume the
    batch with the ones that never landed.

    The rows come off the draft's OWN pending list rather than off the error
    text, intersected with what this call ASKED for: a caller who ran
    `--only walk-e` must not be handed a resume naming eleven rows they
    never wanted. Order is the spec's, so the first pending requested row is
    the one the loop stopped on.

    Returns ``None`` when there is no honest hint to give.
    """
    # ONLY a refusal that happened while generating. `rows` also refuses for
    # being out of order, and at stage `turnaround` every row is "pending"
    # while `reroll-row` is just as illegal as `rows` was — a hint there
    # sends the caller at a second refusal. Caught by the existing
    # out-of-order test, which asserts the flat shape exactly.
    if draft.stage != "rows":
        return None
    # A hint may never cost the caller the refusal it rides on: if reading
    # the draft's state fails here, the flat error shape still travels.
    try:
        pending = draft.status_payload()["pending"]["rows"]
    except Exception:  # noqa: BLE001 - a missing hint beats a lost refusal
        return None
    if only is not None:
        wanted = set(only)
        pending = [key for key in pending if key in wanted]
    if not pending:
        return None
    return _characters_next(
        "reroll-row", "--draft", draft.id, "--row", pending[0],
        alternatives=[
            _characters_next("rows", "--draft", draft.id, "--only", ",".join(pending))
        ],
    )


def _cmd_characters_turnaround(args) -> int:
    return _characters_verb(args, _characters_step_turnaround)


def _cmd_characters_reroll_direction(args) -> int:
    direction = str(getattr(args, "direction", "") or "").strip()
    note = str(getattr(args, "note", "") or "")

    def call(draft):
        result = draft.reroll_direction(direction, note=note)
        return result, (
            f"Draft {draft.id}: direction {result['direction']} re-rolled "
            f"({_attempt_label(result['attempt'], result['attempts'])}, unapproved)"
        )

    return _characters_verb(args, call)


def _cmd_characters_approve_direction(args) -> int:
    approve_all = bool(getattr(args, "approve_all", False))
    direction = str(getattr(args, "direction", "") or "").strip()
    attempt = int(getattr(args, "attempt", -1))

    def call(draft):
        if approve_all:
            return _characters_step_approve_all(draft)
        result = draft.approve_direction(direction, attempt=attempt)
        human = (
            f"Draft {draft.id}: approved {result['direction']} "
            f"{_attempt_label(result['approved'])}, "
            f"{_characters_face_offset_label(result['faceOffset'])}; "
            f"stage is now '{draft.stage}'"
        )
        # Only when the approval ADVANCED the stage — same rule the `--all` arm
        # states at its own site.
        if result.get("advanced"):
            result["next"] = _characters_next("rows", "--draft", draft.id)
        return result, human

    return _characters_verb(args, call)


def _cmd_characters_rows(args) -> int:
    only_text = str(getattr(args, "only", "") or "").strip()
    only = [part.strip() for part in only_text.split(",") if part.strip()] if only_text else None

    def call(draft):
        return _characters_step_rows(draft, only)

    def on_error(draft, exc):
        hint = _characters_rows_next(draft, only)
        return {"next": hint} if hint is not None else None

    return _characters_verb(args, call, on_error=on_error)


def _cmd_characters_reroll_row(args) -> int:
    row_key = str(getattr(args, "row", "") or "").strip()
    note = str(getattr(args, "note", "") or "")

    def call(draft):
        result = draft.reroll_row(row_key, note=note)
        return result, (
            f"Draft {draft.id}: row {result['row']} re-rolled "
            f"({_attempt_label(result['attempt'], result['attempts'])}, approved)"
        )

    return _characters_verb(args, call)


def _cmd_characters_compose(args) -> int:
    accept_text = str(getattr(args, "accept_handedness", "") or "").strip()
    accept = [part.strip() for part in accept_text.split(",") if part.strip()]

    def call(draft):
        return _characters_step_compose(draft, accept)

    return _characters_verb(args, call)
