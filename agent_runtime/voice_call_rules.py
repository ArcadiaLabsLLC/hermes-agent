"""Hermes's voice-call rules for a client that owns its own microphone (RT-FU-ETERNIAS-AGENT-CALL-CAN-USE-HERMES-OWN-INTERRUPT-RULES).

Hermes's voice mode lets the user talk over the agent: ``tools.voice_mode.full_duplex_listen`` opens
the microphone, ``_BargeDetector`` decides when speech interrupts, ``is_tts_echo`` drops the agent's own
voice heard back, and ``is_voice_stop_phrase`` ends the call. Eternia's agent call owns the microphone
itself, so it cannot run that listener; it runs ports of the three rules instead, and hermes stays
the authority over both halves of what those ports need:

* the rules themselves, as ONE shared vectors file (``tests/fixtures/voice_call_rules/vectors.json``,
  written from the live rules by ``tests/agent_runtime/_voice_call_rule_vectors.py``) that every port is tested
  against. :data:`RULE_VECTORS_REVISION` names the file this runtime's rules answer, so a client whose
  port was checked against a different file keeps its half-duplex call instead of guessing;
* the user's settings (``voice.barge_in`` and the rest), read here from the loaded config and served
  by ``runtime.speech.call_settings``. A client adds no setting of its own.

Upstream reads these settings in two private places (``tui_gateway/methods_voice.py``
``_fd_barge_params`` / ``_voice_cfg_dict`` and ``tools/voice_mode_transcript.py``
``_load_voice_stop_phrases``), and no fork module may import an upstream ``_private`` name, so
:func:`call_settings` reads them once more with the same meaning, and
``tests/agent_runtime/test_voice_call_rules.py`` holds it equal to both upstream readers over every
malformed shape they handle.
"""

from __future__ import annotations

import math
from typing import Any

__layer__ = "policy"

__all__ = ["RULE_VECTORS_REVISION", "call_settings"]

#: The first 16 hex digits of the SHA-256 of ``tests/fixtures/voice_call_rules/vectors.json``.
#: ``test_voice_call_rule_vectors.py`` fails when they differ, so a rule change that rewrites the
#: file must move this too, and every client port sees the change.
RULE_VECTORS_REVISION = "0b391f72403c7dc5"

_DEFAULT_GRACE_SECONDS = 0.5


def _loaded_voice_config() -> dict[str, Any]:
    """The ``voice`` block of this runtime's config, ``{}`` when missing or not a mapping."""
    from hermes_cli.config import load_config_readonly

    config = load_config_readonly()
    voice = config.get("voice") if isinstance(config, dict) else None
    return voice if isinstance(voice, dict) else {}


def _threshold_multiplier(voice: dict[str, Any]) -> float:
    """``voice.barge_in_threshold_multiplier``; 0 (unset, empty or malformed) means the rule's default.
    A non-finite value (``nan``, ``inf``) is malformed too: upstream would pass it on, and JSON cannot."""
    try:
        value = float(voice.get("barge_in_threshold_multiplier", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def _grace_ms(voice: dict[str, Any]) -> int:
    """``voice.barge_in_grace_seconds`` in whole milliseconds, never negative; malformed means 0.5 s
    (``inf`` too, where upstream's reader raises)."""
    try:
        return max(0, int(float(voice.get("barge_in_grace_seconds", _DEFAULT_GRACE_SECONDS)) * 1000))
    except (TypeError, ValueError, OverflowError):
        return int(_DEFAULT_GRACE_SECONDS * 1000)


def _stop_phrases(voice: dict[str, Any]) -> list[str]:
    """``voice.stop_phrases`` lowercased and trimmed; ``[]`` turns stopping off; malformed means the default."""
    from tools.voice_mode_transcript import DEFAULT_VOICE_STOP_PHRASES

    raw = voice.get("stop_phrases", DEFAULT_VOICE_STOP_PHRASES)
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, (list, tuple)):
        return [str(p).strip().lower() for p in raw if isinstance(p, (str, int, float)) and str(p).strip()]
    return list(DEFAULT_VOICE_STOP_PHRASES)


def call_settings(voice: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a voice-call client needs to talk over the agent as hermes's own voice mode does.

    ``voice`` is the config's ``voice`` block (default: this runtime's loaded config). The answer:
    ``barge_in`` (talking over the agent interrupts it), ``grace_ms`` (how long after the agent starts
    speaking an onset is ignored), ``threshold_multiplier`` (how far above the room speech must be; 0
    means the vectors' ``default_threshold_multiplier``), ``stop_phrases`` (an utterance that is exactly
    one of these ends the call) and ``rules_revision`` (:data:`RULE_VECTORS_REVISION`)."""
    voice = _loaded_voice_config() if voice is None else voice
    return {
        "barge_in": bool(voice.get("barge_in", True)),
        "grace_ms": _grace_ms(voice),
        "threshold_multiplier": _threshold_multiplier(voice),
        "stop_phrases": _stop_phrases(voice),
        "rules_revision": RULE_VECTORS_REVISION,
    }
