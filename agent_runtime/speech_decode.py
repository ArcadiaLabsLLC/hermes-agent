"""PyAV stays out of the speech pack: faster-whisper runs on arrays, a FILE needs a decoder.

faster-whisper 1.2.1 imports ``av`` at the top of ``faster_whisper/audio.py`` but
uses it only in ``decode_audio`` — which ``WhisperModel.transcribe`` calls for a
path or a file object, never for a numpy array. The speech service hands it
arrays (the Launcher sends raw PCM), so the bundled speech pack ships no PyAV
(66 MiB installed, its largest distribution;
``docs/downstream/bundled-desktop-closure-2026-09-28.md`` § PyAV).

:func:`ensure_av_placeholder` registers a stand-in ``av`` module when the real
one is not installed, and is called before anything imports ``faster_whisper``
for the speech service. Any use of it raises :class:`FileDecodeUnavailable`.
With PyAV installed (full Hermes) it does nothing.

:func:`file_decode_unavailable` is the typed answer for the paths that DO need a
decoder (upstream's ``_transcribe_local`` hands faster-whisper a file path): no
second decode path is bundled, so a voice-note file reads ``unavailable`` with
reason ``file_decode_unavailable`` before any model loads.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import types

__layer__ = "policy"

__all__ = [
    "FILE_DECODE_UNAVAILABLE",
    "FileDecodeUnavailable",
    "ensure_av_placeholder",
    "file_decode_unavailable",
    "is_av_placeholder",
]

#: The typed reason a file transcription reads when no audio decoder is installed.
FILE_DECODE_UNAVAILABLE = "file_decode_unavailable"
_MESSAGE = ("audio file decoding is unavailable: PyAV is not installed (the bundled speech pack "
            "transcribes raw PCM only)")


class FileDecodeUnavailable(RuntimeError):
    """Something tried to decode an audio FILE through the ``av`` placeholder."""

    reason = FILE_DECODE_UNAVAILABLE

    def __init__(self, what: str = "") -> None:
        super().__init__(f"{_MESSAGE}{f' ({what})' if what else ''}")


class _AvPlaceholder(types.ModuleType):
    __hermes_placeholder__ = True

    def __getattr__(self, name: str):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        raise FileDecodeUnavailable(f"av.{name}")


def is_av_placeholder(module: object) -> bool:
    return bool(getattr(type(module), "__hermes_placeholder__", False))


def _real_av_installed() -> bool:
    loaded = sys.modules.get("av")
    if loaded is not None:
        return not is_av_placeholder(loaded)
    try:
        return importlib.util.find_spec("av") is not None
    except (ImportError, ValueError):
        return False


def ensure_av_placeholder() -> bool:
    """Register the ``av`` placeholder unless PyAV is installed. -> True when the placeholder is in place."""
    if _real_av_installed():
        return False
    if not is_av_placeholder(sys.modules.get("av")):
        module = _AvPlaceholder("av", "placeholder: PyAV is not installed; faster-whisper runs on arrays")
        module.__spec__ = importlib.machinery.ModuleSpec("av", None)
        sys.modules["av"] = module
    return True


def _faster_whisper_installed() -> bool:
    try:
        return importlib.util.find_spec("faster_whisper") is not None
    except (ImportError, ValueError):
        return False


def file_decode_unavailable() -> dict | None:
    """``{state, reason, message}`` when faster-whisper is installed WITHOUT PyAV (the bundled
    speech pack), or the placeholder is in place; else ``None`` — with PyAV, or with no
    faster-whisper at all (upstream's own "not installed" path answers that)."""
    if _real_av_installed():
        return None
    if not (is_av_placeholder(sys.modules.get("av")) or _faster_whisper_installed()):
        return None
    return {"state": "unavailable", "reason": FILE_DECODE_UNAVAILABLE, "message": _MESSAGE}
