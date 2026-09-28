"""PyAV stays out of the bundled speech pack: the ``av`` placeholder and the typed file-decode refusal.

Killing mutations are recorded in the commit that added this file.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest

from agent_runtime import speech_decode


@pytest.fixture
def no_pyav(monkeypatch):
    monkeypatch.setitem(sys.modules, "av", None)  # find_spec("av") -> None: not installed


def test_the_placeholder_stands_in_for_a_missing_pyav_and_refuses_any_use(no_pyav):
    assert speech_decode.ensure_av_placeholder() is True
    av = importlib.import_module("av")
    assert speech_decode.is_av_placeholder(av)
    with pytest.raises(speech_decode.FileDecodeUnavailable) as raised:
        av.open("voice-note.ogg")
    assert raised.value.reason == "file_decode_unavailable"
    # Dunder probes (hasattr, inspect, pickle) see an ordinary module, not a decode attempt.
    assert not hasattr(av, "__path__")


def test_a_real_pyav_is_never_replaced(monkeypatch):
    real = types.ModuleType("av")
    monkeypatch.setitem(sys.modules, "av", real)
    assert speech_decode.ensure_av_placeholder() is False
    assert sys.modules["av"] is real
    assert speech_decode.file_decode_unavailable() is None


def test_no_faster_whisper_at_all_is_upstreams_answer_not_a_decode_refusal(no_pyav, monkeypatch):
    monkeypatch.setattr(speech_decode, "_faster_whisper_installed", lambda: False)
    assert speech_decode.file_decode_unavailable() is None
    monkeypatch.setattr(speech_decode, "_faster_whisper_installed", lambda: True)  # positive control
    assert speech_decode.file_decode_unavailable()["reason"] == "file_decode_unavailable"


def test_a_voice_note_file_reads_unavailable_with_a_typed_reason_before_any_model_loads(no_pyav, monkeypatch):
    """Upstream's ``_transcribe_local`` hands faster-whisper a FILE PATH, which needs PyAV.
    Mutation: drop the fork seam in ``_transcribe_local`` -> the loader is reached (and, for real,
    ``import faster_whisper`` fails)."""
    from tools import transcription_tools

    reached = []
    monkeypatch.setattr(speech_decode, "_faster_whisper_installed", lambda: True)  # the speech pack
    monkeypatch.setattr(transcription_tools, "_HAS_FASTER_WHISPER", True)
    monkeypatch.setattr(transcription_tools, "_get_or_load_local_model",
                        lambda *a, **k: reached.append("load") or (_ for _ in ()).throw(RuntimeError("reached")))
    result = transcription_tools._transcribe_local("voice-note.ogg", "base")
    assert (result["success"], result["state"], result["reason"]) == (False, "unavailable", "file_decode_unavailable")
    assert reached == []
    # Positive control: with PyAV installed the same call reaches the loader.
    monkeypatch.setitem(sys.modules, "av", types.ModuleType("av"))
    result = transcription_tools._transcribe_local("voice-note.ogg", "base")
    assert reached == ["load"] and "reached" in result["error"]
