"""The projection side-channel: what one snapshot projection considered, included
and dropped, and why.

* :class:`ProjectionAccountant` — a side-channel a projection records into
  (considered / included / dropped + per-reason tallies + a bounded drop sample).
  Passing ``None`` keeps the projection's behavior byte-for-byte identical, so
  instrumentation is non-invasive.

**By-design vs anomalous drops.** A drop count alone cannot tell a reader whether
a projection is healthy: a bounded lane that keeps the newest 50 of 163 rows
"drops" 113 on every build and is working exactly as specified, while one row
lost to a broken identity join is a defect. Readers that only saw ``dropped``
had to re-derive that distinction from a hardcoded reason-code allowlist on
their side — the Launcher shipped one and it went stale twice (``flow_item_cap``
first, then the persona-chat ``limit``), each time pinning the Mission Control
"projection drops" pill permanently amber on a healthy runtime. The
classification therefore belongs HERE, at the emission site, and rides the
envelope as the additive ``by_design`` key:

* ``by_design=True`` — the drop discloses a **deliberate bound** the projection
  applied on purpose: a cap, a tail window, a page limit, a collapse marker. The
  data is not lost (it stays reachable through the lane's paging/detail fetch)
  and a nonzero count is the steady state, not a symptom.
* ``by_design=False`` (the default) — the drop discloses **lost or inconsistent
  data**: an identity join that did not resolve, a referenced row missing from
  its store, a persona/session mismatch, an unrenderable entry, a redaction
  gate. A nonzero count is something an operator can act on.

The test for a new call site: *would this count still be nonzero on a perfectly
healthy runtime, purely because the projection is bounded?* Yes → ``by_design``.
No → leave it anomalous. Classification is a property of the reason CODE, not of
an individual drop, so a code must be declared the same way at every site that
emits it; once any site declares a code by-design the accountant reports that
code as by-design for the whole projection.

See `Launcher_Brain/20 — Active Initiatives/mission-control-snapshot-architecture.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__layer__ = "models"

# Cap the per-projection sample of concrete drop records carried in the snapshot
# (the full tallies are unbounded in `reasons`; the samples are for the inspector
# and must not bloat the payload).
_MAX_DROP_SAMPLE = 50

#: How many of the 50 slots a BY-DESIGN flood may consume. The remainder is a
#: reserved floor for anomalous records, and that reservation is the whole point
#: (plan ``realm-pull-live-projection`` H3).
#:
#: The sample was one FIFO list, so on a real store the ordering of the drops
#: decided what the operator could see: 132 ``instance_retired`` rows filled all
#: 50 slots before the ONE ``session_not_in_db`` row was recorded, and the
#: launcher's amber "projection drops 1" chip shipped with ``hasDetail == false``
#: — a bare pill with nothing behind it. Naming the offending instance took a
#: Python join over a saved snapshot, which is exactly the cost ``dropSummaries``
#: was built to remove. A by-design drop is the steady state on a healthy
#: runtime; an anomalous one is the only kind an operator can act on, so the
#: bounded budget belongs to the by-design half.
_MAX_BY_DESIGN_DROP_SAMPLE = 40

_TEXT_LIMIT = 200


@dataclass(slots=True)
class DropRecord:
    """One concrete dropped/diverged entity, for the inspector."""

    hop: str
    code: str
    entity_id: str | None = None
    detail: str | None = None
    by_design: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "hop": self.hop,
            "code": self.code,
            "entity_id": self.entity_id,
            "detail": self.detail,
            "by_design": self.by_design,
        }


class ProjectionAccountant:
    """Counts what one snapshot projection considered / included / dropped.

    A projection takes an optional accountant and records into it; the caller
    reads :meth:`summary` afterward. Reason codes are short, stable tokens
    (``persona_mismatch``, ``tail_truncated``, …) so the UI can group them, and
    each code is declared once as a deliberate bound (``by_design=True``) or as
    lost/inconsistent data (the default) — see the module docstring.
    """

    def __init__(self, projection: str):
        self.projection = projection
        self._considered = 0
        self._included = 0
        self._reasons: dict[str, int] = {}
        self._by_design: set[str] = set()
        self._truncated = False
        # TWO lists, one budget each — see ``_MAX_BY_DESIGN_DROP_SAMPLE``. They
        # are re-joined by :meth:`drop_samples`, which is the only reader.
        self._drops_anomalous: list[DropRecord] = []
        self._drops_by_design: list[DropRecord] = []

    def consider(self, n: int = 1) -> None:
        self._considered += max(0, int(n))

    def include(self, n: int = 1) -> None:
        self._included += max(0, int(n))

    def drop(
        self,
        code: str,
        *,
        count: int = 1,
        entity_id: Any = None,
        detail: Any = None,
        hop: str | None = None,
        by_design: bool = False,
    ) -> None:
        """Record ``count`` dropped entities under ``code``.

        ``by_design`` declares this reason code a deliberate bound (cap / tail /
        page limit) rather than lost or inconsistent data. The declaration is
        per-CODE and sticky: it surfaces in :meth:`summary` under ``by_design``
        so a reader can subtract bounded lanes from the anomaly count without
        maintaining its own reason allowlist.

        ``by_design`` ALSO routes which sample budget this record spends, so a
        by-design flood can never starve the anomalous rows the chip is about.
        See :data:`_MAX_BY_DESIGN_DROP_SAMPLE`. Note the split is by the
        argument passed at THIS call, not by the sticky per-code verdict: the
        two agree at every honest site (a code is declared the same way
        everywhere, which the module docstring already requires), and a lane
        that disagreed with itself would be a bug the sample should show rather
        than a reason to re-derive the flag here.
        """

        count = max(1, int(count))
        self._reasons[code] = self._reasons.get(code, 0) + count
        if by_design:
            self._by_design.add(str(code))
        bucket = self._drops_by_design if by_design else self._drops_anomalous
        cap = _MAX_BY_DESIGN_DROP_SAMPLE if by_design else _MAX_DROP_SAMPLE
        if len(bucket) < cap:
            bucket.append(
                DropRecord(
                    hop=hop or self.projection,
                    code=str(code),
                    entity_id=_safe_text(entity_id),
                    detail=_safe_text(detail),
                    by_design=bool(by_design),
                )
            )

    def mark_truncated(self) -> None:
        self._truncated = True

    @property
    def dropped(self) -> int:
        return sum(self._reasons.values())

    def summary(self) -> dict[str, Any]:
        """The per-projection completeness row carried on the parity envelope.

        ``by_design`` is additive (envelope version unchanged): the sorted reason
        codes this projection declared as deliberate bounds. Always present —
        an empty list means every drop recorded here is anomalous. The four
        historical keys are untouched; ``dropped`` still counts EVERY drop, so a
        reader subtracts the by-design reasons itself and an older reader that
        ignores the key behaves exactly as before.
        """

        return {
            "considered": self._considered,
            "included": self._included,
            "dropped": self.dropped,
            "reasons": dict(self._reasons),
            "truncated": self._truncated,
            "by_design": sorted(self._by_design),
        }

    def drop_samples(self) -> list[dict[str, Any]]:
        """The bounded sample of concrete drop records, ANOMALOUS ROWS FIRST.

        **This is a sampling-policy change, not an envelope-shape change**, and
        the distinction is load-bearing: the return type is still
        ``list[dict]`` in the same record shape, ``dropped`` still counts EVERY
        drop, ``reasons`` is still unbounded, and the total is still capped at
        :data:`_MAX_DROP_SAMPLE`. The launcher's ``_isAnomalousDropSample``
        (``mission_control_snapshot.dart:577``) needs no change and MUST need
        none — it filters this list by the ``by_design`` flag each record
        already carries.

        What moved is WHICH records survive the cap. Anomalous first because
        this list is read by an operator answering "what is the amber chip",
        and because the concatenation is what re-imposes the single total: a
        by-design half that was already bounded at
        :data:`_MAX_BY_DESIGN_DROP_SAMPLE` can only be trimmed further here when
        the anomalous half is genuinely large, which is a projection with
        bigger problems than a short sample.
        """

        joined = [*self._drops_anomalous, *self._drops_by_design]
        return [record.as_dict() for record in joined[:_MAX_DROP_SAMPLE]]


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[: _TEXT_LIMIT - 1] + "…" if len(text) > _TEXT_LIMIT else text
