"""The ONE provider seam: the per-call deadline, ``_generate_image`` and ``_draftsman``."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path

from agent.charsheet._upstream_doors import charsheet_setting, imagegen
from agent.charsheet.errors import ProviderTimeout

__layer__ = "stores"


# ───────────────────────────── provider seam ─────────────────────────────

#: Ceiling on ONE provider call, in seconds. Overridable per install through
#: ``charsheet.provider_timeout_seconds`` in ``config.yaml`` (see
#: :func:`provider_timeout_seconds`); ``0`` or a negative value disables the
#: bound entirely and restores the behaviour that preceded it.
#:
#: **Why there is a bound at all.** There was none: this module set no timeout,
#: and :func:`agent.pet.generate.imagegen.generate` has no ``timeout``
#: parameter to pass one through, so the only bound was whatever the resolved
#: backend set for itself — and they disagree by an order of magnitude.
#: ``openrouter`` uses 300 s, ``openai-codex`` a 300 s read timeout, ``krea`` a
#: 180 s poll ceiling; but ``openai`` constructs a bare ``openai.OpenAI()``,
#: whose SDK default is 600 s with retries, so one row could hold a serve pool
#: worker for half an hour with nothing on the hermes side able to say
#: otherwise. That worker is one of four, and the stream subscription already
#: owns one for its lifetime.
#:
#: **Why 300 s.** It is the largest ceiling any shipped backend sets for
#: ITSELF, so hermes never cuts off a provider that is still inside its own
#: contract; and it is far past the 1–2 minutes a healthy generation takes by
#: hermes's own rate estimate (``harness.py::_characters_auto_write``), so a
#: merely slow roll is never mistaken for a wedged one. What it converts is
#: "unbounded" into "one row, bounded" — it is deliberately NOT a bound on the
#: batch, which is a different knob and a different decision.
PROVIDER_TIMEOUT_SECONDS = 300.0


def provider_timeout_seconds() -> float:
    """The configured per-call ceiling, defaulting to :data:`PROVIDER_TIMEOUT_SECONDS`.

    ``config.yaml`` and never an env var: the house rule is that ``.env`` holds
    secrets and every behavioural setting — timeouts included — lives in
    ``config.yaml``. Read lazily (this package must not import ``hermes_cli`` at
    module scope; ``harness.py`` imports it the other way round) and
    defensively, because a pipeline that refused to generate because a config
    file would not parse is a worse failure than the one this bound prevents.
    """

    try:
        value = charsheet_setting("provider_timeout_seconds", PROVIDER_TIMEOUT_SECONDS)
        return float(value)
    except Exception:  # noqa: BLE001 - an unreadable config must not stop a draft
        return PROVIDER_TIMEOUT_SECONDS


def _within_deadline(call, *, seconds: float, prefix: str):
    """Run *call* on a daemon thread and abandon it after *seconds*.

    A non-positive budget runs *call* inline, on this thread — no thread, no
    deadline, byte-identical to the behaviour before the bound existed. That is
    what ``charsheet.provider_timeout_seconds: 0`` buys.

    The worker's exception is re-raised on the caller's thread rather than
    swallowed: a provider's own ``GenerationError`` must reach the verb that
    reports it, and losing a real fault behind a timeout wrapper would be a
    worse bug than the one being fixed.
    """

    if seconds <= 0:
        return call()

    box: dict = {}

    def _run() -> None:
        try:
            box["value"] = call()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller
            box["error"] = exc

    worker = threading.Thread(target=_run, name=f"charsheet-{prefix}", daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise ProviderTimeout(
            f"image generation for {prefix!r} did not answer within {seconds:g}s; "
            "the provider call was abandoned (it may still be running) — retry, "
            "or raise `charsheet.provider_timeout_seconds` in config.yaml",
            safe_details={"prefix": prefix, "seconds": seconds},
        )
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _generate_image(
    prompt: str,
    *,
    reference_images: Sequence[Path] | None,
    aspect_ratio: str,
    prefix: str,
    provider,
) -> Path:
    """The single provider call in the charsheet pipeline; returns one image.

    Every generation in this module funnels through here, so replacing this one
    function drives the whole staged flow offline with synthetic strips. Keep the
    signature stable: it is the test seam.

    It is also the one place a deadline can be applied, which is why it is
    applied here rather than at each of the three call sites. The call runs on a
    worker thread and is abandoned at :func:`provider_timeout_seconds`, raising
    :class:`~agent.charsheet.errors.ProviderTimeout`. The worker is a DAEMON —
    an abandoned call must not keep the process from exiting, which is the
    property that actually returns the serve pool slot — and it is honestly a
    leak until the backend's own socket timeout fires: the thread and its
    connection outlive this function, and nothing here can interrupt a blocking
    HTTP read. A leaked thread traded for a released pool worker and a typed
    refusal is the whole of the bargain.
    """

    def _call() -> list:
        return imagegen.generate(
            prompt,
            n=1,
            reference_images=[Path(ref) for ref in (reference_images or [])],
            provider=provider,
            prefix=prefix,
            aspect_ratio=aspect_ratio,
        )

    images = _within_deadline(_call, seconds=provider_timeout_seconds(), prefix=prefix)
    if not images:
        raise ValueError(f"image generation for {prefix!r} returned no image")
    return Path(images[0])


def _draftsman():
    """WHICH door a generation goes through, resolved at CALL time.

    The real one — unless the declared, default-off seam is armed
    (``HERMES_CHARSHEET_DRAFTSMAN=fake``; see
    :mod:`agent.charsheet.fake_draftsman`, ruling RL-26). Call time rather than
    import time is the whole point: a serve started WITHOUT the variable and a
    child started WITH it are two processes reading two environments, and a
    module-level constant would freeze whichever booted first.

    ``_generate_image`` is looked up as a module global here, so the in-process
    test seam (``monkeypatch.setattr(pipeline, "_generate_image", …)``) is
    untouched and still answers for everything that runs in-process. This
    function only adds the arm a SPAWNED process can reach.
    """
    from agent.charsheet.fake_draftsman import draftsman_from_env

    fake = draftsman_from_env()
    return _generate_image if fake is None else fake
