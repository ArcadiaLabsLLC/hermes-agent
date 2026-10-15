"""The speech pack's own voice runners on onnxruntime: Piper (VITS) voices and Kokoro 82M.

Fork-owned (bundled desktop; owner ruling 2026-09-28, second sitting, item 2).
The pack ships no ``piper-tts`` (GPL-3.0, with espeak-ng compiled in) and no
``kokoro`` / ``phonemizer`` packages: a Piper voice is a VITS ``.onnx`` with its
``.onnx.json``, Kokoro is one ``.onnx`` with a voices file, and the text ->
phoneme step is :mod:`agent_runtime.speech_phonemize`. What each runner does is
what the model's own inference code does, and nothing else:

* **Piper** — ids are ``^``, ``_``, then every phoneme followed by ``_``, then
  ``$`` (the voice's ``phoneme_id_map``); ``scales`` are the voice's
  ``inference`` values; the float output is peak-normalized to int16.
* **Kokoro** — tokens are the phonemes through Kokoro's vocabulary, 0-padded
  both ends, at most 510; ``style`` is the voice preset's row for that length;
  24 kHz float output.

Both synthesize one sentence at a time and yield ``(sample_rate, pcm_s16le)``
per sentence, the shape :class:`agent_runtime.speech_service.SpeechService`
streams.
"""

from __future__ import annotations

import json
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Iterator

from agent_runtime.speech_phonemize import MisakiG2P, OnnxModel, OpenPhonemizer, artifact_files, rp_from_us
from agent_runtime.speech_text import sentences

__layer__ = "stores"

__all__ = ["KOKORO_DEFAULT_PRESET", "KOKORO_SAMPLE_RATE", "KOKORO_VOICES", "KokoroVoice", "PiperVoice",
           "kokoro_presets", "load_voice", "voice_family"]

KOKORO_VOICES = "voices-v1.0.bin"
KOKORO_SAMPLE_RATE = 24000
KOKORO_DEFAULT_PRESET = "af_heart"
_KOKORO_MAX_TOKENS = 510


def voice_family(voice: Path) -> str | None:
    """``piper`` (a ``.onnx.json`` beside it), ``kokoro`` (a voices file beside it), else ``None``."""
    if voice.with_name(voice.name + ".json").exists():
        return "piper"
    if (voice.parent / KOKORO_VOICES).exists():
        return "kokoro"
    return None


def kokoro_presets(voices: Path) -> list[str] | None:
    """The preset names a Kokoro voices file carries, sorted; ``None`` when it is not one.

    The file is an ``.npz`` — a zip of one ``<preset>.npy`` per voice — so the names come from its
    directory, without numpy and without reading a style tensor.
    """
    try:
        with zipfile.ZipFile(voices) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return None
    return sorted(name[:-4] for name in names if name.endswith(".npy") and "/" not in name)


def _to_int16(audio: Any, *, normalize: bool) -> bytes:
    import numpy as np

    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if normalize:
        audio = audio * (1.0 / max(0.01, float(np.abs(audio).max(initial=0.0))))
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class PiperVoice:
    def __init__(self, voice: Path, *, phonemizer: Any = None, model: Any = None) -> None:
        config = json.loads(voice.with_name(voice.name + ".json").read_text(encoding="utf-8"))
        self.sample_rate = int(config["audio"]["sample_rate"])
        self._ids: dict[str, list[int]] = config["phoneme_id_map"]
        inference = config.get("inference") or {}
        self._scales = (float(inference.get("noise_scale", 0.667)), float(inference.get("length_scale", 1.0)),
                        float(inference.get("noise_w", 0.8)))
        self._speakers = int(config.get("num_speakers", 1))
        espeak = config.get("espeak") if isinstance(config.get("espeak"), dict) else {}
        # OpenPhonemizer writes espeak's en-us; a voice trained on espeak's British ``en`` gets it mapped.
        self._dialect = rp_from_us if str(espeak.get("voice", "en-us")).lower() != "en-us" else None
        if phonemizer is None and config.get("phoneme_type", "espeak") != "espeak":
            phonemizer = str  # a ``text`` voice reads characters: no phonemizer at all
        self._phonemize = phonemizer or OpenPhonemizer(*artifact_files("piper", voice))
        self._model = model or OnnxModel(voice, reuse_memory=False)

    def phonemes(self, sentence: str) -> str:
        ipa = self._phonemize(sentence)
        return self._dialect(ipa) if self._dialect is not None else ipa

    def phoneme_ids(self, phonemes: str) -> list[int]:
        pad = self._ids["_"]
        ids = [*self._ids["^"], *pad]
        for symbol in unicodedata.normalize("NFD", phonemes):
            if symbol in self._ids:
                ids += [*self._ids[symbol], *pad]
        return ids + self._ids["$"]

    def synthesize(self, text: str) -> Iterator[tuple[int, bytes]]:
        for sentence in sentences(text):
            ids = self.phoneme_ids(self.phonemes(sentence))
            feed = {"input": [ids], "input_lengths": [len(ids)], "scales": list(self._scales)}
            if self._speakers > 1:
                feed["sid"] = [0]
            yield self.sample_rate, _to_int16(self._model.run(feed), normalize=True)


class KokoroVoice:
    sample_rate = KOKORO_SAMPLE_RATE

    def __init__(self, path: Path, *, preset: str = KOKORO_DEFAULT_PRESET, g2p: Any = None,
                 model: Any = None, styles: Any = None) -> None:
        if styles is None:
            import numpy as np

            styles = np.load(path.parent / KOKORO_VOICES)
        self._g2p = g2p or MisakiG2P(*artifact_files("kokoro", path))
        self._style = styles[preset]
        self._model = model or OnnxModel(path)

    def tokens(self, phonemes: str) -> list[int]:
        vocab = self._g2p.vocab
        return [vocab[p] for p in phonemes if p in vocab]

    def synthesize(self, text: str) -> Iterator[tuple[int, bytes]]:
        for sentence in sentences(text):
            ids = self.tokens(self._g2p(sentence))
            for start in range(0, len(ids), _KOKORO_MAX_TOKENS):
                part = ids[start:start + _KOKORO_MAX_TOKENS]
                # The preset holds one style row per token count: [510, 1, 256].
                feed = {"tokens": [[0, *part, 0]], "style": self._style[len(part)], "speed": [1.0]}
                yield self.sample_rate, _to_int16(self._model.run(feed), normalize=False)


def load_voice(voice: Path, *, preset: str | None = None) -> PiperVoice | KokoroVoice:
    """The voice in ``voice``; ``preset`` picks a Kokoro voice (a Piper voice has none)."""
    family = voice_family(voice)
    if family is None:
        raise FileNotFoundError(f"{voice}: neither a Piper .onnx.json nor {KOKORO_VOICES} beside it")
    if family == "kokoro":
        return KokoroVoice(voice, preset=preset or KOKORO_DEFAULT_PRESET)
    if preset is not None:
        raise ValueError("a Piper voice has no presets")
    return PiperVoice(voice)
