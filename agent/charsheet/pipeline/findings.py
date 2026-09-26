"""The handedness vocabulary: a finding's basis, severity and attribution, and
the acceptance token an operator types for it — one closed set each (rule 14).

A finding is still the ``dict`` :func:`~agent.charsheet.pipeline.validate_sheet`
returns on the wire, read by ``CharacterDraft.compose``, ``characters list`` and
the launcher's bundle warnings; what this module changes is that its three
free-string fields are now members. A ``StrEnum`` member IS its string, so the
JSON a finding serialises to is byte-identical, and a finding read back from a
manifest (a plain ``str``) still compares equal and still keys the two tables
below. Every compare in the package is a member compare, and a word nobody
declared is an ``AttributeError`` at the site, not a silent fall-through.

A vocabulary module: exempt from the 100-line floor (ruling 3).
"""

from __future__ import annotations

from enum import StrEnum

__layer__ = "models"


class MirrorBasis(StrEnum):
    """Which neighbourhood(s) a row was judged — or convicted — against."""

    ROTATION = "rotation"
    STATES = "states"
    BOTH = "rotation and states"


class Severity(StrEnum):
    """What a flagged row does to the install: ``ERROR`` refuses, ``WARNING`` does not."""

    ERROR = "error"
    WARNING = "warning"


class Attribution(StrEnum):
    """How a finding's row was NAMED — or, for the last two, why none could be.

    ``BOTH``: a second, independent basis convicts the row. ``ROTATION``: one
    flagged row alone in its run, nothing contradicting it. ``STATES``: a
    cross-state conviction the rotation does not contradict. ``RUN``: two or
    more flagged together, which the rotation cannot take apart.
    ``CONTRADICTED``: the other basis vouches for the row.
    """

    BOTH = "both"
    ROTATION = "rotation"
    STATES = "states"
    RUN = "run"
    CONTRADICTED = "contradicted"


# How an operator spells WHICH evidence they are waiving, per finding. There is
# no single constant here any more and there must not be one: two shapes block
# now — a row two bases agree about (`rotation+states`) and a row carried by a
# whole mirrored STATE (`states`) — and one hardcoded token would have made the
# second unacceptable at all, which is an error with no override, which is a
# wall. The token is DERIVED from the finding's own basis so the two can never
# drift apart: `validate_sheet` demands it and `mirrored_art_error` prints it,
# both through this one function.
_ACCEPT_BASIS_TOKENS = {
    MirrorBasis.ROTATION: "rotation",
    MirrorBasis.STATES: "states",
    MirrorBasis.BOTH: "rotation+states",
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
    MirrorBasis.ROTATION: "flipping it fits its neighbours in the rotation",
    MirrorBasis.STATES: "flipping it fits the same direction in the other states",
    MirrorBasis.BOTH: (
        "flipping it fits both its neighbours in the rotation and the same "
        "direction in the other states"
    ),
}
