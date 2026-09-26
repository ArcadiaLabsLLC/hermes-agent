"""The doctor's section model: the health vocabulary, the probe context, ``DoctorSection``.

Map: ``agent_runtime/harness_doctor/__init__.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..events import EventLog

__layer__ = "stores"


DEFAULT_WORKTREE_MIN_AGE_SECONDS = 3600

# The health vocabulary every doctor section reports itself in. The verdict is
# DERIVED from these — no section may be examined without contributing one.
#
# ``unknown`` is the load-bearing member and follows the orphan-sweep precedent
# in ``cron/executions.py`` (``status='unknown'`` + "whether side effects ran is
# unknown"): a section whose probe RAISED did not observe health, so it reports
# what it knows — nothing — instead of a plausible default. A defaulted ``ok``
# here is worse than a missing check, because the doctor is the tool an operator
# runs to decide whether to keep investigating.
HEALTH_OK = "ok"
HEALTH_NOTICE = "notice"  # examined, informational only; never moves the verdict
HEALTH_DEFECT = "defect"  # examined, actionable defect observed
HEALTH_UNKNOWN = "unknown"  # NOT examined — the probe failed


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:320]


# ── the section table: ONE declaration, four derived rosters ─────────────────
#
# A doctor section used to be added by editing four hand-maintained lists of one
# set — ``finding_counts``, ``section_health`` and ``findings`` here, plus
# ``detail_sources`` in the CLI printer — with only ``section_health``'s key set
# pinned by a test. A section added to three of the four was therefore counted
# and verdicted while rendering NO operator line, and nothing failed. That is
# the same shape the derived-verdict rework already fixed once by hand (``ok``
# and ``needs_fix`` were computed from two of five sections), which is why this
# one is fixed structurally instead: every roster below is DERIVED from
# :data:`DOCTOR_SECTIONS`, so a new section is one table row and a missing one
# is unspellable.
#
# The table lives at the BOTTOM of this module, where the probes it names are
# defined. Read it first anyway — it is the index to everything above it.


@dataclass(frozen=True)
class _DoctorProbeContext:
    """Every input a probe may read, so all probes share ONE signature.

    A uniform signature is what lets the table hold the probe: a roster of
    sections that could not also name how to run them would be a fifth list to
    keep in step with the other four.
    """

    fix: bool
    dry_run: bool
    worktree_min_age_seconds: int
    include_worktrees: bool
    event_log: EventLog
    snapshot_builder: Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class DoctorSection:
    """One doctor section, declared once.

    * ``name`` — its key in ``summary.section_health``, and the name an
      operator sees on the CLI's per-section line.
    * ``probe`` — the callable that observes it. It must return a dict carrying
      a ``health`` from the vocabulary above; a section whose probe answers
      without one reads ``unknown``, never ``ok``. A probe that reads NOTHING
      from the context declares it optional (``_context=None``), which says so
      in the signature and keeps the probe callable as a bare seam — several
      suites unit-test one section by calling its probe directly, and making
      them build a context to hand a function that ignores it would be
      ceremony, not clarity.
    * ``publish`` — where its report lands in the payload, as
      ``(dotted destination, key inside the report)``. ``None`` publishes the
      whole report dict; a key publishes that member, which is how
      ``snapshot_null_id_rows`` (the row list) and ``snapshot_build`` (whether
      the frame built at all) stay two payload keys from one probe.
    * ``counts`` — the ``summary.finding_counts`` entries it contributes, as
      ``(count name, list key inside the report)``. A count is an OBSERVATION:
      an unexamined section's counts are ``None``, never ``0`` — see
      :func:`run_harness_doctor`.
    * ``detail_source`` — the dotted payload path whose ``error`` the CLI
      prints beside a non-ok section. Usually the section's own report; the
      exception is ``snapshot_null_id_rows``, a bare list whose build outcome
      lives one key over.
    """

    name: str
    probe: Callable[[_DoctorProbeContext], dict[str, Any]]
    publish: tuple[tuple[str, str | None], ...]
    detail_source: str
    counts: tuple[tuple[str, str], ...] = field(default=())
