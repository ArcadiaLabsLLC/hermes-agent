"""The fingerprint HOME: which ``HERMES_HOME`` the fingerprint closes over,
captured once per process and pinned (the module owns that process state
and is its only writer).
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from agent_runtime.core_cache.vocabulary import (
    RECEIPT_FINGERPRINT_HOME_LAZY_CAPTURE,
    logger,
)
from agent_runtime.core_cache.models import FingerprintHomeCapture

__layer__ = "stores"

__all__ = [
    "FINGERPRINT_HOME_CLI_BOOT_SITE",
    "capture_for_harness_command",
    "_capture_fingerprint_home_locked",
    "_fingerprint_home",
    "_fingerprint_home_boot_site",
    "_fingerprint_home_eager",
    "_fingerprint_home_lock",
    "_pinned_to_fingerprint_home",
    "_receipt_fingerprint_home_lazy_capture",
    "capture_fingerprint_home",
    "declare_fingerprint_home_boot_site",
    "fingerprint_home_capture",
    "reset_fingerprint_home",
    "resolved_fingerprint_home",
]


# --------------------------------------------------------------------------- #
# The home this process fingerprints through (MC-2 / P3)
# --------------------------------------------------------------------------- #
#: Resolved ONCE per process, then pinned for the length of every walk.
#:
#: WHAT IT FIXES. Four of the seven classes below bottom out in
#: ``hermes_constants.get_hermes_home()``, whose ladder is the context-local
#: override → ``os.environ["HERMES_HOME"]`` → the platform default. The BUILD
#: ITSELF exports that variable: the ``agents_readiness`` section runs
#: ``profile_readiness.profile_readiness_for_persona`` inside
#: ``profile_context.persona_profile_context``, which sets the context-local
#: override AND writes ``os.environ["HERMES_HOME"]`` process-globally for the
#: length of a per-persona scope. A consult on ANOTHER THREAD — a one-shot
#: hydrate, a status probe, the hub — therefore computed its closure over
#: whichever profile happened to be exported at that instant. Measured in the
#: field 2026-08-18: ``inputs=24344`` and ``inputs=23107`` from ONE process, over
#: ONE store, thirteen seconds apart. A non-filesystem input inside the closure,
#: which is the thing §6.1's bet says must not exist.
#:
#: WHY "RESOLVE THROUGH THE HEAD" IS NOT ON ITS OWN THE FIX. This is the whole
#: soundness argument, so it lives here rather than in a commit message.
#: :func:`agent_runtime.profile_home.get_hermes_head_home` FALLS BACK to
#: ``get_hermes_home()`` whenever no head authority is present — and under an
#: active persona override that fallback IS the override. Worse, the authority it
#: consults first is a ContextVar, and ContextVars do not cross a thread
#: boundary: the head ``persona_profile_context`` records is invisible to the
#: very thread the divergence was measured on, so there the head degenerates to
#: the flipped ambient home. Resolving through the head is NECESSARY and NOT
#: SUFFICIENT. What makes the closure pure is taking that resolution ONCE — at
#: the first fingerprint of the process, which on every real lane is the boot
#: consult, before any persona scope in this process can have run — and pinning
#: it for every walk afterwards.
#:
#: THE RESIDUAL, named rather than discovered later. A process whose FIRST
#: fingerprint is taken while a persona scope is already live captures that
#: scope's home and pins it. That is not silent: ``write_back`` records
#: ``fingerprint_home`` in the sidecar and a later boot judging against it
#: demotes ``home_mismatch`` (see the channel table), which is exactly the field
#: signal that a capture was taken too late.
#:
#: HC-1 (2026-08-22) NARROWS THAT RESIDUAL RATHER THAN RE-ARGUING IT. "The first
#: fingerprint of the process is the boot consult" was an ARGUMENT, and the field
#: falsified it twice on a SINGLE-PROFILE install (2026-08-21 16:04:32 and
#: 2026-08-22 13:36, one boot / three callers demoting ``home_mismatch`` each
#: time — there is no second root for two runs to legitimately disagree about).
#: A long-lived process now DECLARES the boot instant that owes the capture and
#: TAKES it there, so "first use" is a defined point in the lifecycle instead of
#: whichever build or consult won a race. The lazy path below is kept — a plain
#: tool, a test, a subprocess that never boots a serve still has to work — but it
#: is no longer SILENT in a process that declared an instant: see
#: :data:`RECEIPT_FINGERPRINT_HOME_LAZY_CAPTURE`.
_fingerprint_home_lock = threading.Lock()


_fingerprint_home: tuple[Path, bool] | None = None


#: ``True`` when the capture came from :func:`capture_fingerprint_home` — an
#: explicit, named boot instant — and ``False`` when the lazy path took it.
_fingerprint_home_eager: bool = False


#: The boot instant a long-lived process declared it would capture at, or
#: ``None`` in a process that never declared one. This is what makes the lazy
#: receipt below distinguish "a defect recurring" from "an ordinary short-lived
#: process doing the only thing it can".
_fingerprint_home_boot_site: str | None = None


def _capture_fingerprint_home_locked(*, eager: bool) -> tuple[Path, bool]:
    """Take the capture. The caller holds :data:`_fingerprint_home_lock`."""

    global _fingerprint_home, _fingerprint_home_eager
    from agent_runtime.profile_home import get_hermes_head_home, hermes_head_home_is_authoritative

    _fingerprint_home = (
        Path(get_hermes_head_home()),
        bool(hermes_head_home_is_authoritative()),
    )
    _fingerprint_home_eager = eager
    return _fingerprint_home


def _receipt_fingerprint_home_lazy_capture(
    *, home: Path, authoritative: bool, site: str
) -> None:
    """The countable artifact for a capture that was NOT taken where it was owed.

    Emitted only in a process that declared a boot instant, so it can never fire
    for an ordinary short-lived caller. See the channel table row for the census
    rule; the short version is that this line and ``reason=home_mismatch`` are
    the same defect seen from the producing and the judging side, and this one
    arrives a boot earlier.
    """

    logger.warning(
        "snapshot_core_cache %s site=%s home=%s authoritative=%s — the "
        "fingerprint home was captured on first use rather than at the boot "
        "instant that owes it, so whatever scope was live at that moment is now "
        "pinned for the life of this process. A sidecar written from here is "
        "keyed under that home and the next boot will demote it "
        "reason=home_mismatch.",
        RECEIPT_FINGERPRINT_HOME_LAZY_CAPTURE,
        site,
        home,
        "true" if authoritative else "false",
    )


def declare_fingerprint_home_boot_site(site: str) -> None:
    """Name the boot instant at which THIS process owes its capture.

    Deliberately a SEPARATE call from :func:`capture_fingerprint_home`, and the
    separation is the whole mechanism rather than ceremony: the declaration is
    the process saying what it IS (a long-lived runtime with a defined boot
    sequence), the capture is the ACT. Fused into one call, deleting the act
    would delete the ability to notice that it is missing — which is precisely
    how a capture taken too late stayed unattributed until a census rule went
    looking for it. Kept apart, a boot that declares and then does not capture
    reports itself on the first fingerprint it takes.

    A later declaration wins: the CLI's dispatch names the coarse instant, and a
    serve that starts underneath it names its own, more specific one.
    """

    global _fingerprint_home_boot_site
    with _fingerprint_home_lock:
        _fingerprint_home_boot_site = site


def capture_fingerprint_home() -> tuple[Path, bool]:
    """Capture the fingerprint home NOW, at the caller's defined boot instant.

    The eager half of HC-1. Call it from a boot sequence at a point that provably
    precedes any persona scope; everything afterwards — every build, every
    consult, on every thread — then resolves through what was captured here.

    Idempotent, and capture-once still wins: if something already captured
    (lazily, before this call), that capture stands and the lazy receipt has
    already named it. Re-capturing here would silently replace a home some
    fingerprint has already been taken under, which is a worse fault than the one
    being fixed.
    """

    with _fingerprint_home_lock:
        if _fingerprint_home is None:
            return _capture_fingerprint_home_locked(eager=True)
        return _fingerprint_home


def fingerprint_home_capture() -> FingerprintHomeCapture:
    """Observe the capture WITHOUT taking one.

    Its own function rather than exposing the globals, and pointedly not a call
    to :func:`resolved_fingerprint_home`: an observer that captured would destroy
    the very thing it is being asked about — "was this captured eagerly?" cannot
    be answered by a function whose answer is "it is now".
    """

    with _fingerprint_home_lock:
        if _fingerprint_home is None:
            return FingerprintHomeCapture(
                home=None,
                authoritative=False,
                eager=False,
                boot_site=_fingerprint_home_boot_site,
            )
        return FingerprintHomeCapture(
            home=_fingerprint_home[0],
            authoritative=_fingerprint_home[1],
            eager=_fingerprint_home_eager,
            boot_site=_fingerprint_home_boot_site,
        )


def resolved_fingerprint_home() -> tuple[Path, bool]:
    """``(home, authoritative)`` for this process — captured once, then frozen.

    ``authoritative`` is :func:`agent_runtime.profile_home.hermes_head_home_is_authoritative`
    as it read AT CAPTURE TIME. ``False`` means the head had degenerated to the
    ambient resolution, so the recorded home is only as good as the moment it was
    taken. That is a fact a demote should be able to name, which is why it is
    persisted beside the home instead of dropped.

    The lazy capture here is the FALLBACK, not the design: a process that
    declared a boot instant and still lands in this branch is reporting the
    defect HC-1 exists to retire, and says so on the log rather than quietly
    pinning whatever home the winning caller happened to be running under.
    """

    lazy_site: str | None = None
    with _fingerprint_home_lock:
        if _fingerprint_home is None:
            captured = _capture_fingerprint_home_locked(eager=False)
            lazy_site = _fingerprint_home_boot_site
        else:
            captured = _fingerprint_home
    # OUTSIDE the lock. A logging handler is arbitrary third-party code and this
    # lock is taken on every fingerprint walk; emitting under it would put a
    # handler's I/O in front of every stat in the process.
    if lazy_site is not None:
        _receipt_fingerprint_home_lazy_capture(
            home=captured[0], authoritative=captured[1], site=lazy_site
        )
    return captured


def reset_fingerprint_home() -> None:
    """Forget the captured home, as a fresh process would. Tests only.

    Its own function rather than only a line inside
    :func:`reset_process_state` because the per-test environment sandbox moves
    ``HERMES_HOME`` between cases, and a capture frozen from case 1 would answer
    case 2 with a directory pytest has already deleted — a fingerprint that is
    stable for the wrong reason. The ``tests/agent_runtime`` conftest drops it
    autouse, the same way it drops the profile-runner resolve memo.

    Drops the boot-site declaration too, and that is load-bearing rather than
    tidy: a case that drove a serve boot would otherwise leave every LATER case
    in the session claiming to be a serve, and each one's ordinary lazy capture
    would emit the receipt that means a defect recurred.
    """

    global _fingerprint_home, _fingerprint_home_eager, _fingerprint_home_boot_site
    with _fingerprint_home_lock:
        _fingerprint_home = None
        _fingerprint_home_eager = False
        _fingerprint_home_boot_site = None


@contextmanager
def _pinned_to_fingerprint_home() -> Iterator[None]:
    """Resolve inside this block through the captured home, not the ambient one.

    The mechanism is :func:`hermes_constants.set_hermes_home_override` — the same
    context-local override ``persona_profile_context`` installs, applied in the
    opposite direction and only for the length of a stat. Deliberately NOT a
    hand-composed ``home / "config.yaml"`` at each site: every class below keeps
    resolving through its OWN path authority, which is §6.1's first mitigation
    ("no second list free to drift") and is precisely the property a second copy
    of a path rule would give up. The override is context-local by construction,
    so pinning the walking thread cannot perturb a persona turn running beside
    it.

    Applied PER CLASS rather than around the whole walk, so each class states why
    it needs the pin and each is independently falsifiable: dropping the pin from
    one class reds that class's witness alone.
    """

    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    home, _authoritative = resolved_fingerprint_home()
    token = set_hermes_home_override(home)
    try:
        yield
    finally:
        reset_hermes_home_override(token)


# ── the CLI's capture instant (moved from hermes_cli/harness.py, queue row) ──
# The site keeps its pre-plugin spelling: receipts and sidecars already carry it.
FINGERPRINT_HOME_CLI_BOOT_SITE = "hermes_cli.main:harness_command_dispatch"


def capture_for_harness_command(args) -> None:
    """Capture the core cache's fingerprint home BEFORE the command runs (HC-1).

    THE RULE, and why it is applied here and only here. ``core_cache`` freezes
    the Hermes home its input closure is stat'd under on FIRST USE, and a first
    use that lands inside ``profile_context.persona_profile_context`` pins that
    persona's home for the life of the process — after which any sidecar this
    process writes is keyed under it, and the NEXT boot demotes the pair
    ``reason=home_mismatch``. A one-shot CLI is not exempt from that: ``hermes
    harness chat send`` runs a persona turn through
    ``profile_runner._execute_agent_run``, whose whole body is inside that
    scope, and a tool in that turn reaching the snapshot is a first fingerprint
    taken under the override. The poisoned pair then outlives the process.

    SCOPE, decided on evidence rather than on caution: only ``hermes harness …``
    can reach this lane at all — ``core_cache``/``agent_runtime.snapshot`` are
    imported by ``hermes_cli.harness``, ``harness_support`` and the four
    ``harness_parts`` modules, and by nothing else under ``hermes_cli``. It runs
    from ``hermes_cli.harness._harness_entry``, which only the harness tree's handlers carry, so
    no other command pays for it.

    ``hermes harness serve`` passes through here too, and that is deliberate
    rather than redundant: this is the earliest instant in the process the
    command owns, and ``serve_loop`` re-declares its own, more specific site
    under it. Capture-once means the second call is an observation, not a
    second answer.

    Best effort by contract: an instrument must never be why a command fails.
    """

    if getattr(args, "command", None) != "harness":
        return
    try:
        declare_fingerprint_home_boot_site(FINGERPRINT_HOME_CLI_BOOT_SITE)
        capture_fingerprint_home()
    except Exception:
        pass
