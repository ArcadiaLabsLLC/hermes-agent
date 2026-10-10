"""Native wire accounting and redaction; upstream owns non-user size policy.

Operator composition keeps its explicit per-part bounds. Other content and tool
arguments must survive projection without another size cut. Real flush/replay
coverage lives in test_native_result_policy_downstream.py.
"""
from __future__ import annotations

import logging

import pytest

from agent_runtime.persona_chat_continuity import (
    BOUND_ACTION_DROPPED,
    BOUND_ACTION_TRUNCATED,
    BOUND_PART_CONTENT,
    BOUND_PART_SKILL_PRELOAD,
    BOUND_PART_TOOL_ARGUMENTS,
    CONTENT_BOUND_PARTS,
    WIRE_BOUNDARY,
    ContentBoundNote,
    WireBoundaryRow,
    native_wire_row,
    record_wire_boundary_cut,
    record_wire_boundary_drift,
    safe_native_message,
)
from agent_runtime.runtime_hud import (
    SKILL_PRELOAD_CODEC,
    SKILL_PRELOAD_DELIVERY_SNAPSHOT,
    render_runtime_context_envelope,
    render_skill_preload_envelope,
    skill_preload_revision,
    split_composed_user_row,
)


# The qa persona's required preload measured 54,114 chars on 2026-08-09 — ~3x
# the flat cap. Fixtures are sized to genuinely exceed every bound they test: a
# fixture that fits under the limit makes the bounded and the unbounded boundary
# identical and would pass against either.
#: A distinctive marker at the very END, so "the whole body arrived" is checked
#: rather than inferred from a length. A trailing SPACE would be stripped by the
#: envelope codec, which is a fixture artifact, not a bound — hence a real tail.
SKILL_BODY_TAIL = "PITFALL: a refused screenshot means relaunch, never improvise."


def _skill_body(chars: int = 54_114) -> str:
    filler = "Step: capture the window through the MCP marionette path. " * (chars // 58 + 1)
    return filler[: chars - len(SKILL_BODY_TAIL)] + SKILL_BODY_TAIL


def _composed_row(*, message: str = "screenshot the NEWS tab", skill_chars: int = 54_114) -> str:
    body = _skill_body(skill_chars)
    preload = render_skill_preload_envelope(
        skill_names=["launcher-stagec-mcp-screenshot"],
        skill_preload_content=body,
        revision=skill_preload_revision(body),
        delivery=SKILL_PRELOAD_DELIVERY_SNAPSHOT,
    )
    hud = render_runtime_context_envelope(
        context_id="ctx_0123456789abcdef",
        revision="hud_" + "a" * 16,
        delivery="snapshot",
        situational_hud_content="## Runtime Situation\nscope: eternia · launcher",
        volatile_content="Turn budget: with under 270 s left, wrap up and report.",
    )
    return "\n\n".join([message, preload, hud])


# --------------------------------------------------------------------------- #
# THE INVARIANT
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role", ["user", "assistant", "tool", "system"])
def test_a_short_row_reaches_the_wire_whole_and_unbounded(role: str):
    bound = native_wire_row({"role": role, "content": "a modest sentence"})

    assert bound.row["content"] == "a modest sentence"
    assert bound.notes == ()
    assert bound.wire_chars == bound.redacted_chars
    assert bound.unaccounted_loss == 0
    assert bound.holds


@pytest.mark.parametrize("role", ["assistant", "tool", "system"])
def test_non_user_content_arrives_whole_without_bound_notes(role: str):
    content = "x" * 300_000 + " END OF RESULT"
    bound = native_wire_row({"role": role, "content": content})

    assert bound.row["content"] == content
    assert bound.wire_chars == bound.redacted_chars == len(content)
    assert bound.notes == ()
    assert bound.accounted_loss == 0
    assert bound.holds


def test_the_composed_operator_row_closes_its_arithmetic():
    """The three-part row: the split, the per-part bounds and the rejoin must
    lose nothing that the notes do not name."""

    composed = _composed_row()
    assert len(composed) > 50_000, "fixture must exceed the retired 20k cap"

    bound = native_wire_row({"role": "user", "content": composed})

    # Nothing was cut at all here — the per-part ceiling holds 256 KiB.
    assert bound.notes == ()
    assert bound.wire_chars == bound.redacted_chars == len(composed)
    assert bound.holds
    # ...and the skill survived intact, which is the F1 regression itself.
    body = SKILL_PRELOAD_CODEC.body(split_composed_user_row(bound.row["content"]).skill_preload)
    assert body is not None
    assert body.endswith(SKILL_BODY_TAIL), "the skill's TAIL must survive, not just its length"
    assert len(body) == len(_skill_body())


def test_a_dropped_part_is_accounted_as_a_drop_not_a_silent_absence():
    """A part too large to survive is dropped and SAID SO. An honest absence is
    the design; an unrecorded one is the defect."""

    composed = _composed_row(skill_chars=400_000)
    bound = native_wire_row({"role": "user", "content": composed})

    assert bound.bounded
    assert any(n.action == BOUND_ACTION_DROPPED for n in bound.notes) or any(
        n.action == BOUND_ACTION_TRUNCATED for n in bound.notes
    )
    assert bound.unaccounted_loss == 0, (
        f"unexplained residue of {bound.unaccounted_loss} chars; notes were "
        f"{[(n.part, n.action, n.original_chars, n.bounded_chars) for n in bound.notes]}"
    )
    assert bound.holds


def test_tool_call_arguments_arrive_whole_without_bound_notes():
    arguments = '{"source":"' + "a" * 12_000 + ' END"}'
    bound = native_wire_row({
        "role": "assistant", "content": "calling a tool",
        "tool_calls": [{"id": "c1", "function": {"name": "terminal", "arguments": arguments}}],
    })

    assert bound.row["tool_calls"][0]["function"]["arguments"] == arguments
    assert bound.notes == ()
    assert bound.argument_loss == 0
    assert bound.holds


def test_argument_loss_cannot_cancel_a_content_residue():
    """Argument loss is REPORTED, never netted into the content arithmetic.

    Summing both into ``accounted_loss`` would let a truncated argument blob
    cancel out a real content residue and drive ``unaccounted_loss`` to zero —
    a check that hides exactly what it exists to find. Asserted on a
    hand-built row so the two quantities can be forced apart.
    """

    row = WireBoundaryRow(
        row={"role": "assistant", "content": "..."},
        notes=(
            # An argument bound big enough to swallow the content residue below.
            ContentBoundNote(
                part=BOUND_PART_TOOL_ARGUMENTS,
                action=BOUND_ACTION_TRUNCATED,
                original_chars=9_000,
                bounded_chars=4_000,
                limit=4_000,
            ),
        ),
        submitted_chars=1_000,
        redacted_chars=1_000,
        wire_chars=600,
    )

    assert row.accounted_loss == 0, "an argument note must not count as content accounting"
    assert row.argument_loss == 5_000
    assert row.unaccounted_loss == 400
    assert not row.holds


def test_applying_the_boundary_twice_is_stable_and_loses_nothing_further():
    """Warm memory and cold persistence share this boundary, so a second pass
    must be a no-op. If it were not, a resumed session would drift from a live
    one by exactly one more truncation per reload."""

    once = native_wire_row({"role": "assistant", "content": "y" * 30_000})
    twice = native_wire_row(once.row)

    assert twice.row["content"] == once.row["content"]
    assert twice.notes == ()
    assert twice.holds


# --------------------------------------------------------------------------- #
# ANTI-VACUITY — the residue detector must actually discriminate
# --------------------------------------------------------------------------- #
def test_the_residue_detector_catches_an_unaccounted_loss():
    """A ``holds`` that could never be False would pass this file forever.

    This is the shape of the defect the whole change targets: content shorter on
    the wire than it was submitted, with no note naming the difference.
    """

    silent = WireBoundaryRow(
        row={"role": "assistant", "content": "z" * 20_000},
        notes=(),
        submitted_chars=30_000,
        redacted_chars=30_000,
        wire_chars=20_000,
    )

    assert silent.unaccounted_loss == 10_000
    assert not silent.holds

    drift = silent.drift_row()
    assert drift is not None
    assert drift["boundary"] == WIRE_BOUNDARY
    assert drift["unaccounted_loss"] == 10_000
    assert drift["role"] == "assistant"


def test_redaction_is_not_reported_as_an_unaccounted_bound():
    """Redaction legitimately changes length. Folding it into the residue would
    make every row carrying a secret look like a silent amputation, and a check
    that cries wolf gets muted."""

    bound = native_wire_row({"role": "assistant", "content": "api_key: topsecretvalue"})

    assert "topsecretvalue" not in bound.row["content"]
    assert bound.submitted_chars != bound.redacted_chars or bound.holds
    assert bound.unaccounted_loss == 0
    assert bound.holds


def test_the_content_part_split_is_exhaustive():
    """Every content part must be inside ``CONTENT_BOUND_PARTS``; a new part
    added outside it would silently stop counting toward the arithmetic."""

    assert BOUND_PART_CONTENT in CONTENT_BOUND_PARTS
    assert BOUND_PART_SKILL_PRELOAD in CONTENT_BOUND_PARTS
    assert BOUND_PART_TOOL_ARGUMENTS not in CONTENT_BOUND_PARTS


# --------------------------------------------------------------------------- #
# The fail-loud row
# --------------------------------------------------------------------------- #
def test_record_wire_boundary_drift_is_silent_when_the_invariant_holds():
    bound = native_wire_row({"role": "user", "content": "fine"})

    assert record_wire_boundary_drift(bound) is None


def test_record_wire_boundary_drift_reports_loudly_and_never_raises(caplog):
    """Fail LOUD, not fatal. This runs on the live turn loop before the first
    provider call; raising would lose a healthy turn over an accounting bug."""

    silent = WireBoundaryRow(
        row={"role": "tool", "content": "z" * 10},
        notes=(),
        submitted_chars=5_000,
        redacted_chars=5_000,
        wire_chars=10,
    )

    with caplog.at_level(logging.ERROR):
        row = record_wire_boundary_drift(silent)

    assert row is not None and row["unaccounted_loss"] == 4_990
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    assert "unaccounted" in caplog.text


# --------------------------------------------------------------------------- #
# The coupling site itself
# --------------------------------------------------------------------------- #



def test_safe_native_message_still_returns_the_plain_row():
    """Back-compat: every existing caller keeps working, and gets the same row
    the typed form carries."""

    message = {"role": "assistant", "content": "w" * 30_000}

    assert safe_native_message(message) == native_wire_row(message).row
    assert isinstance(safe_native_message(message), dict)





# --------------------------------------------------------------------------- #
# The accounted cut gets a receipt too
# --------------------------------------------------------------------------- #
def test_record_wire_boundary_cut_names_the_tool_and_the_sizes_never_the_content(caplog):
    # Preserve receipts for accounted degradation independently of retired cuts.
    bound = WireBoundaryRow(
        row={"role": "tool", "tool_name": "launcher_generated_list", "content": "SENTINEL"},
        notes=(ContentBoundNote(BOUND_PART_CONTENT, BOUND_ACTION_TRUNCATED, 30_000, 20_000, 20_000),),
    )
    with caplog.at_level(logging.WARNING):
        notes = record_wire_boundary_cut(bound)

    assert notes == bound.notes and len(notes) == 1
    assert "launcher_generated_list" in caplog.text
    assert "30000->20000/20000" in caplog.text
    assert "SENTINEL" not in caplog.text


def test_record_wire_boundary_cut_is_silent_for_a_row_that_arrived_whole(caplog):
    bound = native_wire_row({"role": "tool", "tool_name": "t", "content": "small"})

    with caplog.at_level(logging.WARNING):
        assert record_wire_boundary_cut(bound) == ()

    assert "wire boundary cut" not in caplog.text


def test_record_wire_boundary_cut_leaves_the_user_row_to_its_own_warning(caplog):
    """The composed user row already warns from its bounding with per-part
    arithmetic; a second line for the same cut would read as two cuts."""

    bound = native_wire_row({"role": "user", "content": "u" * 30_000})
    assert bound.notes

    with caplog.at_level(logging.WARNING):
        assert record_wire_boundary_cut(bound) == ()

    assert "wire boundary cut" not in caplog.text
