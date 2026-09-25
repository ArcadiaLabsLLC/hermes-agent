"""``detect_mirrored_art`` and the acceptance-basis tokens."""

from __future__ import annotations

from agent.charsheet.spec import RowSpec, SheetSpec, row_key

from .geometry import _open_rgba, turnaround_order
from .registration import MIRROR_GAIN_THRESHOLD, _gain, _row_cells, _run_findings, _seam_distance, _seam_evidence, _seam_record, registration_window

__layer__ = "lanes"


def detect_mirrored_art(spec: SheetSpec, image) -> dict:
    """Which authored rows are drawn as the MIRROR of the direction they claim.

    Two independent passes, both asking the same question — *would flipping this
    one row horizontally make it fit the art it has to agree with noticeably
    better than it does as drawn?* — of two different neighbourhoods:

    * **the rotation** (``basis: "rotation"``): the authored directions of ONE
      state, walked in turnaround order. Answers a single mis-drawn row.
    * **the states** (``basis: "states"``): the SAME direction across every
      state, all of which must face the same way. Answers a whole state drawn
      mirrored — the case ``add_state`` makes reachable in one batch, since it
      generates all of a new state's rows against one reference and one prompt,
      which is exactly how the `ne` defect arose along the other axis.

    Pure per-pixel distance — no skin tone, hue, silhouette or art-style
    assumption — and no reference art, because a rotation sequence and a set of
    states are each their own reference.

    Why the rotation pass scores a ROW and not a seam: a seam only says the two
    rows either side of it disagree, never which of them is wrong. Summing the
    seams a row touches, before and after flipping IT, is what attributes the
    fault — and it is also what makes a nearly symmetric neighbour harmless
    rather than dangerous. The front and back views are close to their own mirror
    images, so a seam against one carries almost no handedness information; here
    it lands as a near-zero term that dilutes the ratio, not as a vote that can
    veto it. On the live defective sheet ``idle-ne``'s seam against ``idle-n``
    preferred the UNFLIPPED art by 2.1% — noise off a symmetric view — and the
    two-neighbour rule that this replaced, which required both neighbours to
    agree, cleared the row on that vote. It was mirrored, in all three states,
    and had shipped.

    Why the state pass needs THREE states: across one pair a disagreement cannot
    say which of the two rows is the mirrored one — the same reason the
    rotation's end rows are never judged. With three or more, a row is convicted
    only when a strict majority of ALL the states that draw the direction
    disagree with it — that is, only when its camp is a strict MINORITY — and
    the quietest of those disagreeing readings is what ``gain`` reports for this
    basis. The default sheet has two states, so this pass says nothing until a
    third arrives, and an EVEN number of states that splits evenly convicts
    nobody: two camps of equal size, and nothing inside the sheet says which one
    is mirrored.

    **Two shapes refuse an install; everything else warns.** A single-basis
    finding about a single ROW carries ``severity: "warning"``. Two carry
    ``severity: "error"``:

    * ``basis: "rotation and states"`` — two independent neighbourhoods agreeing
      about the SAME row. The two populations do not separate at the threshold
      on one basis: the quietest true reading measured on real art is +6.78%
      rotation / +7.64% states, and the loudest false one, a CORRECT row
      displaced sideways, is +18.75%. The line sits inside both populations, so
      no value of :data:`MIRROR_GAIN_THRESHOLD` separates them and what changed
      instead is what one reading is permitted to do.
    * **a WHOLE STATE reading as mirrored** — every row of one state that the
      cross-state pass could judge, at least two of them, flagged. Such findings
      carry ``wholeState`` (the state's flagged rows, in sheet order) and are
      errors on ONE basis or two (owner ruling 2026-08-25). The rotation cannot
      corroborate this one *by algebra* — a wholly mirrored state is a fixed
      point of it — so demanding a second basis would mean never refusing the
      defect ``add_state`` is most likely to produce. A single row mirroring is
      NOT escalated: that is the warning above, and the ``>= 2`` guard is what
      keeps a 4-way scheme (one cross-state-judged row per state) out of here.

    The consequence for the default character is stated rather than hidden:
    ``characters start`` creates ``idle:6, walk:8``, two states have no
    cross-state pass at all, so on that DEFAULT sheet neither error shape is
    reachable and this check can only ever warn.

    **What this cannot see, written down so nobody has to rediscover it.** The
    measure is invariant under flipping every row at once, because
    ``distance(flip(a), flip(b)) == distance(a, b)``. A character drawn
    consistently mirrored on ALL rows is therefore a perfect fixed point and
    passes cleanly — and so is one whose every STATE is mirrored, since the state
    pass is a consensus and a unanimous one convicts nobody. Nothing internal to
    a sheet can catch either: the sheet is self-consistent, and only the world
    outside it — the launcher's screen axes — says which way is east. The same
    algebra bounds the third blind spot: a contiguous BLOCK of mirrored rows in
    one rotation is visible only at the block's edges.

    **The rotation's two END rows are never judged**, and neither is any row
    whose neighbour is blank: a row is judged only when it has a measurable seam
    on EACH side. One seam cannot say which of the two rows either side of it is
    the mirrored one — flipping either scores identically. Both halves of that
    were measured: on the correct 4-way ``cobalt-robot-courier`` sheet the back
    view's single seam preferred the mirror by 11%, and an earlier draft of this
    check refused that character's install over it, while the same seam diluted
    to 1.9% inside its interior neighbour's two-seam score.

    **A 4-way scheme is nearly blind here and that is worth knowing**: it authors
    ``s, e, n``, so its ONE interior row's two neighbours are both near-symmetric
    views and neither carries much handedness information. Mirroring that row on
    the live 4-way character moved its score from +1.9% to -1.9% — the check
    passes it either way. The 8-way scheme judges ``se, e, ne``, each against at
    least one profile or diagonal, which is where the signal lives.

    Returns ``{"flagged": [...], "judged": [...], "unjudged": [...]}``. Both
    lists carry a ``basis``, and every row of the sheet is named at least once
    across the two: a row may be judged by one pass and unjudged by the other
    (a 4-way sheet's ``e`` row is judged in the rotation and unjudged across
    states, because there is only one state), but never both under the SAME
    basis. ``judged`` carries the gain of every row a pass could answer for, over
    the threshold or under it, so the margin is a readable fact rather than
    something a caller re-derives.
    ``flagged`` is the subset worth acting on after attribution. Each entry
    quotes the seams that voted and carries ``severity`` (above), ``attributed``
    and ``attribution`` — plus ``wholeState`` on the rows a whole mirrored state
    carries, holding that state's flagged rows in sheet order. ``attributed`` is
    the honest half: ``True`` means the
    evidence NAMES this row, and the entry then lists any ``corroborating`` rows
    that read high because of it ("do not re-roll them"); ``False`` means a
    neighbourhood is wrong but nothing here can say which row, and the entry
    lists the whole run under ``alternatives`` instead. ``unjudged`` is the
    accounting: a row this cannot answer for is named with the reason rather
    than silently dropped.
    """
    rgba = _open_rgba(image)
    window = registration_window(spec.frame_w)
    rows_by_key = {row.key: row for row in spec.rows()}
    cells_by_key: dict[str, list] = {}

    def cells(row: RowSpec) -> list:
        if row.key not in cells_by_key:
            cells_by_key[row.key] = _row_cells(rgba, spec, row)
        return cells_by_key[row.key]

    def blank(row: RowSpec) -> bool:
        return not any(cell.getbbox() for cell in cells(row))

    judged: list[dict] = []
    unjudged: list[dict] = []

    # The states pass runs FIRST, because the rotation's attribution reads it.
    # Naming a row as the culprit of a rotation run is a claim the rotation
    # cannot make on its own (see _attribute_run), so the second basis has to
    # exist before the first one is allowed to point at anybody.
    state_flagged: list[dict] = []
    states_judged_per_state: dict[str, int] = {}
    directional = [state for state in spec.states if state.directional]
    for direction in turnaround_order(spec.scheme.authored)[1:-1]:
        drawn = [
            rows_by_key[row_key(state.name, direction)]
            for state in directional
            if not blank(rows_by_key[row_key(state.name, direction)])
        ]
        if len(drawn) < 3:
            unjudged.append(
                {
                    "rows": [row.key for row in drawn],
                    "basis": "states",
                    "reason": (
                        f"only {len(drawn)} state(s) draw {direction!r} — across one "
                        "pair a disagreement cannot say WHICH of the two states is "
                        "mirrored, so this read needs three"
                    ),
                }
            )
            continue
        across: dict[tuple[str, str], dict] = {}
        for index, left in enumerate(drawn):
            for right in drawn[index + 1 :]:
                direct, flipped = _seam_distance(
                    cells(left), cells(right), window=window
                )
                across[(left.key, right.key)] = _seam_record(
                    left.key, right.key, direct, flipped
                )
        # A strict majority of ALL the states that draw this direction, never a
        # majority of the OTHER ones. `len(pairs) // 2 + 1` was 2 of 3 on a
        # four-state sheet, so a 2-2 split left every row inside a "majority"
        # and convicted all four — the two CORRECT ones at +14.31% basis
        # `states`, with no corroborating marker at all, while their rotation
        # readings sat at -15.97%. `len(drawn) // 2 + 1` is the same number for
        # three states and for five, and one more for four, which is what makes
        # an even split convict nobody: a row is convicted only when its camp is
        # a strict MINORITY of the states — the same argument that forces the
        # three-state minimum above.
        needed = len(drawn) // 2 + 1
        entries: list[dict] = []
        against: dict[str, int] = {}
        for row in drawn:
            pairs = [seam for pair, seam in across.items() if row.key in pair]
            ranked = sorted(
                (seam for seam in pairs if _gain([seam]) is not None),
                key=lambda seam: _gain([seam]),
                reverse=True,
            )
            if len(ranked) < needed:
                # Never a bare `continue`: a row that vanishes from the payload
                # reads exactly like a clean one. Same accounting rule as the
                # rotation's `as_drawn <= 0` case.
                unjudged.append(
                    {
                        "rows": [row.key],
                        "basis": "states",
                        "reason": (
                            f"only {len(ranked)} of its {len(pairs)} cross-state "
                            "pairs measure anything, and a conviction here needs "
                            f"{needed} of {len(drawn)} states to disagree with it"
                        ),
                    }
                )
                continue
            against[row.key] = sum(
                1 for seam in ranked if _gain([seam]) >= MIRROR_GAIN_THRESHOLD
            )
            entries.append(
                {
                    "row": row.key,
                    "state": row.state,
                    "direction": row.direction,
                    "gain": _gain([ranked[needed - 1]]),
                    "basis": "states",
                    "seams": _seam_evidence(row.key, ranked[:needed]),
                }
            )
        # An even split is every row landing exactly ONE short of the conviction
        # line — which is why it is spelled `needed - 1` and not `len(drawn) //
        # 2`. The two are equal, and writing the second one made this branch
        # able to mask a wrong `needed`: with the old `len(pairs) // 2 + 1` the
        # conviction line drops to 2 of 4 and every row of a 2-2 split is
        # convicted, but a branch keyed to its own arithmetic still fired first
        # and hid it. One knob, one place.
        if (
            len(drawn) % 2 == 0
            and len(against) == len(drawn)
            and all(count == needed - 1 for count in against.values())
        ):
            # Every state disagrees with exactly half the others: two camps of
            # equal size, and nothing inside the sheet says which camp holds the
            # mirrored art. Reporting a gain here would read as a clean pass.
            unjudged.append(
                {
                    "rows": [row.key for row in drawn],
                    "basis": "states",
                    "reason": (
                        f"the {len(drawn)} states that draw {direction!r} split "
                        f"evenly, {needed - 1} against {needed - 1} — neither "
                        "camp is a "
                        "minority, so this pass cannot say which half is mirrored"
                    ),
                }
            )
            continue
        judged.extend(entries)
        # Counted per STATE, not per direction, because the whole-state rule
        # below asks "did EVERY row of this state that anyone could answer for
        # read as a mirror?" — and a row this pass gave up on (unjudged above)
        # must not be silently counted as agreement in either direction.
        for entry in entries:
            states_judged_per_state[entry["state"]] = (
                states_judged_per_state.get(entry["state"], 0) + 1
            )
        state_flagged.extend(
            dict(entry, corroborating=[], alternatives=[])
            for entry in entries
            if entry["gain"] >= MIRROR_GAIN_THRESHOLD
        )

    cross_gain = {
        entry["row"]: entry["gain"] for entry in judged if entry["basis"] == "states"
    }
    convicted_per_state: dict[str, int] = {}
    for finding in state_flagged:
        convicted_per_state[finding["state"]] = (
            convicted_per_state.get(finding["state"], 0) + 1
        )

    # THE WHOLE-STATE RULE (owner ruling 2026-08-25). A state whose EVERY
    # cross-state-judged row reads as a mirror is a whole state drawn backwards,
    # and that is an ERROR on this one basis. It is not a second basis and it
    # must not be mistaken for one: it is a second-order CONSENSUS over the same
    # pass, and it is the only reading that can exist for this defect, because
    # the rotation is a FIXED POINT of a wholly mirrored state — flip every row
    # of one state and its chain still fits itself perfectly. Waiting for a
    # second basis here means waiting forever.
    #
    # The shape is exactly what `add_state` produces: all of a new state's rows
    # in ONE batch, against one reference and one prompt — the same generation
    # shape that drew `ne` backwards three times along the other axis.
    #
    # TWO guards, and both are load-bearing:
    #
    #   * `>= 2` rows. A state with ONE judged row is the single-row case, which
    #     the ruling leaves a WARNING; escalating it would be the 4-way scheme's
    #     whole answer (`turnaround_order(...)[1:-1]` is one direction there), so
    #     without this guard a 4-way sheet would refuse on exactly the reading
    #     the owner declined to escalate.
    #   * EVERY judged row, never a majority. One row of the state judged CLEAN
    #     is the sheet saying the state faces the right way somewhere, which is
    #     a contiguous block of mirrored rows, not a mirrored state.
    #
    # What this buys and what it costs, said out loud: it makes the `add-state`
    # defect blocking on the only pass that can see it, and it makes a whole
    # state of CORRECT art that is displaced in every direction (one prop, drawn
    # in every direction of one state — the false population measured at +18.75%
    # on a single row) blocking too. That is what `--accept-handedness` is for,
    # and why the override had to work per row on this finding as well.
    whole_state_rows: dict[str, list[str]] = {}
    for state, convicted in convicted_per_state.items():
        if convicted >= 2 and convicted == states_judged_per_state.get(state, 0):
            whole_state_rows[state] = sorted(
                (
                    finding["row"]
                    for finding in state_flagged
                    if finding["state"] == state
                ),
                key=lambda key: rows_by_key[key].index,
            )

    # The rotation pass.
    rotation_scored: list[tuple[int, dict]] = []
    per_state_scored: list[list[tuple[int, dict]]] = []
    for state in spec.states:
        if not state.directional:
            unjudged.append(
                {
                    "rows": [row_key(state.name, None)],
                    "basis": "rotation and states",
                    "reason": (
                        "state is not directional — it has no rotation to walk, "
                        "and no other state holds a copy of a direction to "
                        "compare it against"
                    ),
                }
            )
            continue

        chain = [
            rows_by_key[row_key(state.name, direction)]
            for direction in turnaround_order(spec.scheme.authored)
        ]
        seams: dict[tuple[str, str], dict] = {}
        for left, right in zip(chain, chain[1:]):
            if blank(left) or blank(right):
                continue
            direct, flipped = _seam_distance(cells(left), cells(right), window=window)
            seams[(left.key, right.key)] = _seam_record(
                left.key, right.key, direct, flipped
            )

        scored: list[tuple[int, dict]] = []
        for position, row in enumerate(chain):
            if blank(row):
                unjudged.append(
                    {
                        "rows": [row.key],
                        "basis": "rotation",
                        "reason": "the row is empty — an empty row has no facing",
                    }
                )
                continue
            before = seams.get((chain[position - 1].key, row.key)) if position else None
            after = (
                seams.get((row.key, chain[position + 1].key))
                if position + 1 < len(chain)
                else None
            )
            touching = [seam for seam in (before, after) if seam is not None]
            if len(touching) < 2:
                unjudged.append(
                    {
                        "rows": [row.key],
                        "basis": "rotation",
                        "reason": (
                            f"{len(touching)} of the two seams it needs — a row is "
                            "judged only with a measurable neighbour on EACH side, "
                            "because one seam cannot say WHICH of the two rows "
                            "either side of it is mirrored (flipping either scores "
                            "identically). The ends of the rotation always land "
                            "here, and they are also the two views closest to their "
                            "own mirror image, so there is little to see"
                        ),
                    }
                )
                continue
            gain = _gain(touching)
            if gain is None:
                unjudged.append(
                    {
                        "rows": [row.key],
                        "basis": "rotation",
                        "reason": (
                            "both of its seams measure zero — a row identical to "
                            "its neighbours carries no handedness signal"
                        ),
                    }
                )
                continue
            scored.append(
                (
                    position,
                    {
                        "row": row.key,
                        "state": row.state,
                        "direction": row.direction,
                        "gain": gain,
                        "basis": "rotation",
                        "seams": _seam_evidence(row.key, touching),
                    },
                )
            )

        judged.extend(entry for _position, entry in scored)
        per_state_scored.append(scored)
        rotation_scored.extend(scored)

    # A direction the rotation suspects in a strict MAJORITY of the states that
    # judged it is the signature of a direction drawn the same wrong way every
    # time — which is exactly the case the cross-state pass is blind to, so its
    # silence there must not be read as a character reference.
    judged_per_direction: dict[str, int] = {}
    over_per_direction: dict[str, int] = {}
    for _position, entry in rotation_scored:
        judged_per_direction[entry["direction"]] = (
            judged_per_direction.get(entry["direction"], 0) + 1
        )
        if entry["gain"] >= MIRROR_GAIN_THRESHOLD:
            over_per_direction[entry["direction"]] = (
                over_per_direction.get(entry["direction"], 0) + 1
            )
    suspected = {
        direction
        for direction, seen in judged_per_direction.items()
        if seen >= 2 and over_per_direction.get(direction, 0) * 2 > seen
    }

    rotation_flagged: list[dict] = []
    for scored in per_state_scored:
        rotation_flagged.extend(_run_findings(scored, cross_gain, suspected))

    flagged: list[dict] = list(rotation_flagged)
    by_row = {finding["row"]: finding for finding in flagged}
    for finding in state_flagged:
        # The cross-state pass names one row, never a neighbourhood, so it has
        # no run to attribute. It still has to answer the same question the
        # rotation does: is this row named on evidence, or only ranked? A row
        # whose rotation reading CONTRADICTS the states one is named only when
        # its state is convicted as a whole — the `add-state` shape, where the
        # rotation is a fixed point and its silence means nothing.
        rotation_gain = next(
            (
                entry["gain"]
                for entry in judged
                if entry["row"] == finding["row"] and entry["basis"] == "rotation"
            ),
            None,
        )
        finding["attributed"] = not (
            rotation_gain is not None
            and rotation_gain < 0
            and convicted_per_state.get(finding["state"], 0) < 2
        )
        finding["attribution"] = "states" if finding["attributed"] else "contradicted"
        existing = by_row.get(finding["row"])
        if existing is None:
            # A row that only rode along as corroborating now has evidence of its
            # own: stop telling the operator not to touch it.
            for other in flagged:
                other["corroborating"] = [
                    entry
                    for entry in other["corroborating"]
                    if entry["row"] != finding["row"]
                ]
            flagged.append(finding)
            by_row[finding["row"]] = finding
        else:
            existing["basis"] = "rotation and states"
            existing["seams"] = existing["seams"] + finding["seams"]
            existing["gain"] = max(existing["gain"], finding["gain"])
            existing["attributed"] = True
            existing["attribution"] = "both"
            existing["alternatives"] = []

    for finding in flagged:
        # THE SEVERITY RULE, in two lines because there are two ways to refuse.
        #
        # (1) A single basis about a single ROW warns; two independent bases
        # agreeing about it REFUSE. The two populations do not separate on one
        # reading — measured in both directions, the true floor on real art is
        # +6.78% rotation / +7.64% states (`jumping-se` mirrored, caught by
        # neither pass) and the false ceiling on CORRECT art displaced sideways
        # is +18.75%. An 8% line does not sit BETWEEN two populations there; it
        # sits inside both of them. Moving the number cannot fix that, so what
        # moved instead is what a single reading is allowed to DO.
        #
        # (2) A whole STATE reading as mirrored REFUSES on one basis or two
        # (`whole_state_rows` above). That is not the rule in (1) relaxed: the
        # evidence is every judged row of the state agreeing, which the rotation
        # can never corroborate because it is blind to this defect by algebra.
        # `wholeState` carries the roster rather than a bare flag, so the
        # message can name the state's rows and nothing has to re-derive them.
        if "states" in finding["basis"] and finding["row"] in whole_state_rows.get(
            finding["state"], ()
        ):
            finding["wholeState"] = list(whole_state_rows[finding["state"]])
        finding["severity"] = (
            "error"
            if finding["basis"] == "rotation and states" or finding.get("wholeState")
            else "warning"
        )

    flagged.sort(key=lambda finding: rows_by_key[finding["row"]].index)
    return {"flagged": flagged, "judged": judged, "unjudged": unjudged}


# How an operator spells WHICH evidence they are waiving, per finding. There is
# no single constant here any more and there must not be one: two shapes block
# now — a row two bases agree about (`rotation+states`) and a row carried by a
# whole mirrored STATE (`states`) — and one hardcoded token would have made the
# second unacceptable at all, which is an error with no override, which is a
# wall. The token is DERIVED from the finding's own basis so the two can never
# drift apart: `validate_sheet` demands it and `mirrored_art_error` prints it,
# both through this one function.
_ACCEPT_BASIS_TOKENS = {
    "rotation": "rotation",
    "states": "states",
    "rotation and states": "rotation+states",
}


def accept_basis_token(basis: str) -> str:
    """The ``--accept-handedness`` basis token for a finding on *basis*.

    Public because the refusal that demands the spelling and the message that
    teaches it are in two places, and a second spelling of this map is how an
    operator gets told to type something the validator then rejects.
    """
    try:
        return _ACCEPT_BASIS_TOKENS[basis]
    except KeyError:  # pragma: no cover - a new basis would be a code change
        raise ValueError(f"no acceptance token for basis {basis!r}") from None


_MIRROR_BASIS = {
    "rotation": "flipping it fits its neighbours in the rotation",
    "states": "flipping it fits the same direction in the other states",
    "rotation and states": (
        "flipping it fits both its neighbours in the rotation and the same "
        "direction in the other states"
    ),
}
