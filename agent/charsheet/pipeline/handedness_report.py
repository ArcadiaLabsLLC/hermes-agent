"""The operator-facing rendering of a handedness finding."""

from __future__ import annotations

from collections.abc import Sequence

from .handedness import _MIRROR_BASIS, accept_basis_token

__layer__ = "lanes"


# The one spelling of "this row was named, and here is what it costs to obey a
# name that is wrong". Every branch of :func:`mirrored_art_error` quotes it
# exactly once, on the line that hands over an action — which is why the two
# ERROR branches carry it now. Before this it rode only on the corroborating
# tail, so a refusal with no corroborating rows told an operator to re-roll and
# never told them the re-roll could not be taken back.
_REROLL_IS_ONE_WAY = (
    "a re-roll auto-approves and there is no approve-row verb to undo it, so "
    "obeying a name that is wrong spends correct approved art"
)


# Why ``--accept-handedness`` is NOT the cheap door, said on the line that
# offers it. The override is the only way past a refusal (``compose`` has no
# other), so leaving it out of the text left an operator who had LOOKED at the
# art with one instruction — re-roll — that destroys the approved art they had
# just judged correct. It is shown, and it is shown with its price: a re-roll is
# private, an acceptance is a permanent public fact about the character.
_ACCEPT_IS_A_RECORD = (
    "an acceptance writes {row, gain, basis} onto the installed manifest as "
    "handednessAccepted, and characters list, sprite_payload and the launcher's "
    "bundle warnings all republish it for the life of the character"
)


def _block(headline: str, rows: Sequence[tuple[str, str]]) -> str:
    """A finding rendered as a headline plus one ``label: value`` line per fact.

    **No hard wrap, deliberately.** The whole diagnostic used to be one
    unwrapped paragraph — measured 2026-08-26 on the live sheet at 1206
    characters on a single line, and 1519 when a malformed acceptance made the
    validator restate the same finding a second time underneath the acceptance
    error. That survives a terminal by accident and cannot be rendered on a
    console card at all, which is the launcher surface that has to show exactly
    this text.

    Wrapping it here would only move the problem: a column count chosen in this
    module is wrong for every consumer that is not an 80-column terminal. What
    both consumers need is SEPARABLE FACTS — a first line that stands alone, and
    one self-contained field per line after it. A terminal soft-wraps them; a
    card wraps each field on its own width, or shows the headline and discloses
    the rest.
    """
    width = max(len(label) for label, _text in rows) + 1
    return "\n".join(
        [headline] + [f"  {label + ':':<{width}}  {text}" for label, text in rows]
    )


def _disposition(finding: dict, accepted: bool) -> str:
    """The headline's verdict word: what this finding DID to the compose.

    Read off ``severity`` rather than typed per branch, so a branch cannot
    announce a refusal the severity rule did not make.
    """
    if accepted:
        return "WAIVED by the operator, this install carries it"
    return "REFUSED" if finding.get("severity") == "error" else "WARNING, does not block"


def _corroborating_rows(finding: dict) -> list[tuple[str, str]]:
    """The "these neighbours are NOT separate faults" line, when there are any.

    Its "Do NOT re-roll them" is the load-bearing half: a mirrored row pulls
    both its neighbours toward the line, and an operator who obeys a three-row
    refusal literally spends two correct approved attempts that no verb can give
    back. The one-way cost itself is stated once per block, on the action line
    below this one, so it is said where the verb is handed over rather than
    twice in one message.
    """
    if not finding.get("corroborating"):
        return []
    names = ", ".join(
        f"'{entry['row']}' {entry['gain'] * 100:.0f}%"
        for entry in finding["corroborating"]
    )
    return [
        (
            "also high",
            f"{names} read high too and are NOT separate faults: a mirrored row "
            "pulls the seams of the rows either side of it toward the line as "
            "well. Do NOT re-roll them. Fix this row, compose again, and judge "
            "what is left then.",
        )
    ]


def _accept_rows(
    finding: dict, accepted: bool, *, looked: str
) -> list[tuple[str, str]]:
    """The override lines — the door, and its price; or the record of its use.

    Two lines rather than one because they are two facts, and the whole shape
    of this message is one self-contained fact per line. Splitting them also
    keeps the longest line in the block off 450 characters, which is where the
    unsplit version landed.

    The token comes from :func:`accept_basis_token` on this finding's own basis,
    which is the same call :func:`validate_sheet` makes when it decides whether
    to honour what the operator typed. One function, so what an operator is told
    to type and what the validator accepts cannot drift apart.
    """
    token = f"{finding['row']}:{accept_basis_token(finding['basis'])}"
    if accepted:
        return [
            (
                "recorded",
                f"--accept-handedness {token} was given, and it is a fact about "
                f"this character now, not a refusal that vanished: "
                f"{_ACCEPT_IS_A_RECORD}.",
            )
        ]
    return [
        (
            "accept",
            f"only if you have LOOKED at {looked} and the art is right: compose "
            f"--accept-handedness {token}. It is the more expensive door, not the "
            "cheaper one, and it is not a way to make the check quiet.",
        ),
        (
            "on record",
            f"{_ACCEPT_IS_A_RECORD}. Say in the turn what you saw on the art.",
        ),
    ]


def mirrored_art_error(
    finding: dict, *, acceptance_error: str | None = None, accepted: bool = False
) -> str:
    """The operator-facing text for ONE :func:`detect_mirrored_art` finding.

    Public so the message has a single spelling: the validator raises it and a
    test asserts it, and a second copy is how a refusal starts naming a verb
    that no longer exists.

    It renders four different things, and the difference is the point.
    ``severity: "error"`` blocks a compose and is the only severity that hands
    the operator a ``reroll-row`` command; it arrives in two shapes, and they
    get two texts because they have two remedies — two independent bases
    agreeing about ONE row (re-roll that row), and a WHOLE STATE whose every
    judged row reads mirrored (re-roll the state, and do not expect a second
    basis that cannot exist). A single-basis finding about a single row WARNS
    and says so, because one basis does not separate the two populations. An
    UNATTRIBUTED finding names no row at all: it lists the run and says the
    rotation alone cannot tell which of them is the fault, which is true in the
    two shapes where the run's maximum is an innocent row (see
    :func:`_attribute_run`).

    **Both blocking shapes show the override, and that is a decision rather than
    a slip** (2026-08-26). It was already shown on one of them — the whole-state
    branch spelled ``--accept-handedness`` and the two-basis branch did not — so
    what shipped was not a policy of not advertising the hatch but a drift
    between two spellings of the same thing, the exact class
    :func:`accept_basis_token` exists to retire. Owner ruling 18 tightens this
    gate *because* the row-named override is reachable, and an override an
    operator can only find by guessing the flag name is not reachable in any
    sense that argument can use. It is shown AFTER the re-roll line, conditional
    on having LOOKED at the strip, and priced (:data:`_ACCEPT_IS_A_RECORD`) so it
    cannot read as the cheap way out: a re-roll is private and only ever costs
    art, while an acceptance follows the character to the manifest, to
    ``characters list``, to ``sprite_payload`` and to the launcher's bundle
    warnings for good.

    *acceptance_error* folds the operator's own malformed ``--accept-handedness``
    token into THIS row's block. It exists because the two used to be separate
    entries in ``errors`` about the same row, so a bare row name printed the
    acceptance complaint and then the entire diagnostic again underneath it.

    Every branch that teaches an override spells it through
    :func:`accept_basis_token` on THIS finding's basis, so the token an operator
    is told to type is the token :func:`validate_sheet` will accept.
    """
    row = finding["row"]
    evidence = "; ".join(
        f"vs '{seam['with']}' {seam['distance']:.2f} -> "
        f"{seam['mirroredDistance']:.2f} flipped"
        for seam in finding["seams"]
    )
    corrupts = (
        "A mirrored authored row corrupts the derived direction with it, "
        "because the consumer builds that one by flipping this row."
    )
    rows: list[tuple[str, str]] = []
    if acceptance_error:
        rows.append(("you typed", acceptance_error))

    if not finding.get("attributed", True):
        alternatives = finding.get("alternatives") or [finding]
        ranked = ", ".join(
            f"'{entry['row']}' {entry['gain'] * 100:.0f}%" for entry in alternatives
        )
        why = (
            "flagged rows next to each other raise each other, and the rotation "
            "cannot say which of them started it — a correct row slid sideways, "
            "and a correct row flanked by two mirrored ones, both put an "
            "innocent row at the top. Only a second, independent read takes a "
            "run apart, and a third state is what provides one"
            if finding.get("attribution") == "run"
            else "the same direction in the other states vouches for it, so this "
            "reads as PLACEMENT — a prop or a framing drift — rather than "
            "handedness"
        )
        rows += [
            ("ranked", ranked),
            ("seams", evidence),
            (
                "why",
                f"it is NOT attributed to {row!r} or to any other single row — "
                f"{why}",
            ),
            ("corrupts", corrupts),
            (
                "look",
                "crop these rows and look at them. Do not re-roll on this alone: "
                f"{_REROLL_IS_ONE_WAY}. Reach for --accept-handedness only on a "
                "finding that actually blocks.",
            ),
        ]
        return _block(
            f"one of {len(alternatives)} rows in {finding['state']!r} reads as a "
            f"MIRROR and this pass cannot say which — "
            f"{_disposition(finding, accepted)}",
            rows,
        )

    if finding.get("wholeState"):
        roster = ", ".join(f"'{key}'" for key in finding["wholeState"])
        rows += [
            (
                "state",
                f"every one of the {len(finding['wholeState'])} rows of "
                f"{finding['state']!r} this pass could judge ({roster}) reads as "
                "the mirror of the direction it claims",
            ),
            (
                "reads",
                f"this row: {_MIRROR_BASIS[finding['basis']]} "
                f"{finding['gain'] * 100:.0f}% better",
            ),
            ("seams", evidence),
            (
                "blocks",
                "ONE basis refuses here, and that is not the single-row rule "
                "relaxed — a wholly mirrored state is a FIXED POINT of the "
                "rotation pass (flip every row of a state and its chain still "
                "fits itself), so the rotation's silence is not a second opinion "
                "and no second basis can ever arrive. It is the shape add-state "
                "produces: one batch, one reference, one prompt.",
            ),
            ("corrupts", corrupts),
        ]
        rows += _corroborating_rows(finding)
        rows += [
            (
                "re-roll",
                f"characters reroll-row --row {row} --note ... — and the same for "
                "the state's other rows, with the facing spelled in frame terms; "
                "look at the strips before composing. Be sure first: "
                f"{_REROLL_IS_ONE_WAY}.",
            ),
        ]
        rows += _accept_rows(finding, accepted, looked="the strips")
        return _block(
            f"row {row!r} belongs to a WHOLE STATE that reads as MIRRORED — "
            f"{_disposition(finding, accepted)}",
            rows,
        )

    if finding.get("severity") == "error":
        rows += [
            (
                "reads",
                f"{_MIRROR_BASIS[finding['basis']]} "
                f"{finding['gain'] * 100:.0f}% better",
            ),
            ("seams", evidence),
            (
                "blocks",
                "two independent reads agree about this one row, which is what "
                "refuses an install",
            ),
            ("corrupts", corrupts),
        ]
        rows += _corroborating_rows(finding)
        rows += [
            (
                "re-roll",
                f"characters reroll-row --row {row} --note ... — with the facing "
                "spelled in frame terms, and look at the strip before composing. "
                f"Be sure first: {_REROLL_IS_ONE_WAY}.",
            ),
        ]
        rows += _accept_rows(finding, accepted, looked="this row's strip")
        return _block(
            f"row {row!r} looks drawn as the MIRROR of {finding['direction']!r} — "
            f"{_disposition(finding, accepted)}",
            rows,
        )

    rows += [
        (
            "reads",
            f"{_MIRROR_BASIS[finding['basis']]} {finding['gain'] * 100:.0f}% better",
        ),
        ("seams", evidence),
        (
            "warns",
            "one basis is a WARNING and does not block the install — the true and "
            "false populations overlap on a single read (the quietest true "
            "reading measured on real art is +6.8%, the loudest false one "
            "+18.8%), so this cannot be told apart from placement on its own",
        ),
        ("corrupts", corrupts),
    ]
    rows += _corroborating_rows(finding)
    rows += [
        ("look", f"crop this row and look before you re-roll: {_REROLL_IS_ONE_WAY}."),
        (
            "next",
            "a third state is what gives the cross-state pass something to say, "
            "and two bases agreeing is what refuses an install.",
        ),
    ]
    return _block(
        f"row {row!r} reads as the MIRROR of {finding['direction']!r} on ONE basis "
        f"— {_disposition(finding, accepted)}",
        rows,
    )


def handedness_summary(handedness: dict) -> str:
    """One line saying what the handedness check could and could not answer for.

    Counts ROWS, not findings, and "unjudged" here means *no pass answered for
    it* — a row the rotation judged is not reported as unjudged just because the
    cross-state pass had only one state to work with.

    Exists because the payload it summarises was, until 2026-08-25, read by
    nothing outside this module and its tests: ``compose`` printed ``WxH`` and
    raised on a refusal, so on a clean sheet an operator never learned that six
    of fifteen rows were never judged, and on a refusal the whole payload — the
    unjudged list included — was discarded exactly when it mattered.
    """
    judged = {entry["row"] for entry in handedness["judged"]}
    unjudged = sorted(
        {row for entry in handedness["unjudged"] for row in entry["rows"]} - judged
    )
    parts = [f"{len(judged)} row(s) judged"]
    accepted = handedness.get("accepted") or []
    accepted_rows = {entry["row"] for entry in accepted}
    blocking = [
        finding
        for finding in handedness["flagged"]
        if finding.get("severity") == "error" and finding["row"] not in accepted_rows
    ]
    warned = [
        finding
        for finding in handedness["flagged"]
        if finding.get("severity") != "error" and finding["row"] not in accepted_rows
    ]
    if blocking:
        parts.append(f"{len(blocking)} refused")
    if warned:
        # Named, not just counted: a warning no longer blocks, so the only thing
        # standing between it and a shipped mirrored row is somebody reading it.
        parts.append(
            f"{len(warned)} warned ({', '.join(sorted(f['row'] for f in warned))})"
        )
    if accepted:
        parts.append(
            f"{len(accepted)} accepted by the operator "
            f"({', '.join(entry['row'] for entry in accepted)})"
        )
    if unjudged:
        parts.append(f"{len(unjudged)} unjudged ({', '.join(unjudged)})")
    return "handedness: " + ", ".join(parts)
