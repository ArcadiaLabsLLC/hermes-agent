"""The speech pack's GPL-free text -> phonemes -> model-input path (no espeak-ng, no torch).

``agent_runtime.speech_text`` / ``speech_phonemize`` / ``speech_onnx_voice``. The ONNX models are
stood in by fakes that answer nested lists (the CI venv has neither onnxruntime nor numpy); the
artifacts' JSON sidecars are written small, in the real shape. Each check names its killing
mutation; the reds are recorded in the commit that added this file.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import speech_onnx_voice, speech_phonemize, speech_text
from agent_runtime.speech_phonemize import MisakiG2P, OpenPhonemizer, rp_from_us


class FakeModel:
    """Answers ``rows`` from a function of the feeds; counts calls."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def rows(self, feeds):
        self.calls.append(feeds)
        return self.answer(feeds)


def _one_hot(tokens, width):
    return [[1.0 if i == t else 0.0 for i in range(width)] for t in tokens]


# ── numbers ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text, spoken", [
    ("at 3:45 PM", "at three forty-five P M"),
    ("at 9:05", "at nine oh five"),
    ("on September 28th, 2026", "on September twenty-eighth, twenty twenty-six"),
    ("12.5 percent", "twelve point five percent"),
    ("1,234 files", "one thousand two hundred thirty-four files"),
    ("2000 and 21st", "two thousand and twenty-first"),
])
def test_digits_are_spoken_as_english_words(text, spoken):
    """The pack ships no num2words (LGPL). Mutation: drop the clock-time rule -> "three:forty-five"."""
    assert speech_text.spell_numbers(text) == spoken


def test_sentences_split_after_final_punctuation_only():
    assert speech_text.sentences("Welcome back. It is 3.5 miles!  Go") == ["Welcome back.", "It is 3.5 miles!", "Go"]


# ── OpenPhonemizer (Piper) ──────────────────────────────────────────────────

_TEXT = {"_": 0, "<en_us>": 1, "<end>": 2, **{c: 3 + i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}}
_PHONEMES = {"0": "_", "1": "<en_us>", "2": "<end>", "3": "z", "4": "ɔ", "5": "ɹ", "6": "b"}


def _openphonemizer(tmp_path, answer):
    sidecar = tmp_path / "op.json"
    sidecar.write_text(json.dumps({"text_tokens": _TEXT, "phoneme_tokens": _PHONEMES, "char_repeats": 3,
                                   "start_index": 1, "end_index": 2,
                                   "dictionary": {"welcome": "wˈɛlkʌm", "back": "bˈæk"}}), encoding="utf-8")
    model = FakeModel(answer)
    return OpenPhonemizer(tmp_path / "op.onnx", sidecar, model=model), model


def test_openphonemizer_reads_its_dictionary_and_asks_the_model_only_for_other_words(tmp_path):
    """Frame-level argmax -> blanks dropped, repeats merged, cut at ``<end>`` (DeepPhonemizer's
    decode). Mutation: stop merging repeats -> ``zzɔɔɹɹ``; let a blank end a repeat -> ``zzɔɹ``;
    drop the ``<end>`` cut -> a trailing ``b``."""
    frames = [1, 3, 3, 0, 3, 4, 4, 5, 2, 6]  # <en_us> z z _ z ɔ ɔ ɹ <end> b
    phonemizer, model = _openphonemizer(tmp_path, lambda feeds: [_one_hot(frames, 7)])
    assert phonemizer("Welcome back, Zorb.") == "wˈɛlkʌm bˈæk, zɔɹ ."
    assert len(model.calls) == 1
    ids = model.calls[0]["text"][0]
    assert ids[0] == 1 and ids[-1] == 2 and ids[1:4] == [_TEXT["z"]] * 3  # char_repeats, start/end tokens


def test_openphonemizer_says_initialisms_by_letter_name_and_product_names_its_way(tmp_path):
    """Mutation: drop the letter-name rule -> the model is asked for ``P`` and ``M`` as sounds;
    drop the product lexicon -> the model is asked for "Eternia"."""
    phonemizer, model = _openphonemizer(tmp_path, lambda feeds: [_one_hot([2], 7)])
    assert phonemizer("PM Eternia") == "pˈiː-ˈɛm " + speech_phonemize.PRODUCT_LEXICON["eternia"]["piper"]
    assert model.calls == []


def test_us_ipa_maps_to_the_british_espeak_voice_it_was_trained_on():
    """``en`` voices read ``ɑː`` as the "dark" vowel. Mutation: drop the U+E000 hold on ``ɑːɹ`` ->
    "dark" becomes ``dˈɒk``; drop ``("ɑː", "ɒ")`` -> "fox" stays ``fˈɑːks`` (heard as "farks"); drop
    the before-a-vowel guard -> "very" becomes ``vˈeəi``."""
    assert rp_from_us("dˈɑːɹk fˈɑːks ˈoʊvɚ bᵻfˈoːɹ hɪɹ") == "dˈɑːk fˈɒks ˈəʊvə bɪfˈɔː hɪə"
    assert rp_from_us("ɹˈʌn vˈɛɹi sˈɑːɹi") == "ɹˈʌn vˈɛɹi sˈɒɹi"  # an ɹ before a vowel stays


def _piper_config(tmp_path, voice):
    onnx = tmp_path / "v.onnx"
    onnx.write_bytes(b"\1")
    (tmp_path / "v.onnx.json").write_text(json.dumps({
        "audio": {"sample_rate": 22050}, "espeak": {"voice": voice}, "num_speakers": 1,
        "phoneme_id_map": {"_": [0], "^": [1], "$": [2], "d": [3], "ɑ": [4], "ː": [5], "k": [6], "ɒ": [7]}}),
        encoding="utf-8")
    return onnx


@pytest.mark.parametrize("dialect, ids", [
    ("en-us", [1, 0, 3, 0, 4, 0, 5, 0, 6, 0, 2]),  # dˈɑːk: the stress mark has no id and is skipped
    ("en", [1, 0, 3, 0, 7, 0, 6, 0, 2]),           # the same US phonemes, as the British voice reads them
])
def test_piper_ids_intersperse_pad_and_follow_the_voices_espeak_dialect(dialect, ids, tmp_path):
    """Piper's ids: ``^ _`` then each phoneme and ``_``, then ``$``. Mutation: map every voice
    (or none) -> one row red; drop the pad after each phoneme -> both red."""
    voice = speech_onnx_voice.PiperVoice(_piper_config(tmp_path, dialect), phonemizer=lambda _t: "dˈɑːk",
                                         model=object())
    assert voice.phoneme_ids(voice.phonemes("dock")) == ids


# ── misaki (Kokoro) ─────────────────────────────────────────────────────────

_GRAPHEMES = "____abcdefghijklmnopqrstuvwxyz"
_MISAKI_PHONEMES = "____zɔɹb"


def _misaki(tmp_path, answer):
    sidecar = tmp_path / "g2p.json"
    sidecar.write_text(json.dumps({
        "graphemes": _GRAPHEMES, "phonemes": _MISAKI_PHONEMES, "start_id": 1, "bos_id": 1, "eos_id": 2,
        "unknown_id": 3, "max_steps": 16, "kokoro_vocab": {"f": 1, "I": 2, "l": 3, "z": 4, " ": 5, ".": 6},
        "gold": {"file": "fˈIl", "to": "tə", "download": "dˈWnlˌOd", "P": "pˈi", "M": "ˈɛm",
                 "read": {"DEFAULT": "ɹˈid", "VBD": "ɹˈɛd"}},
        "silver": {}}), encoding="utf-8")
    model = FakeModel(answer)
    return MisakiG2P(tmp_path / "g2p.onnx", sidecar, model=model), model


def _greedy(sequence):
    """A fake BART: at step n it answers ``sequence[n]``."""
    return lambda feeds: [[_one_hot([0], 8)[0]] * (len(feeds["decoder_input_ids"][0]) - 1)
                          + [_one_hot([sequence[len(feeds["decoder_input_ids"][0]) - 1]], 8)[0]]]


def test_misaki_never_drops_a_word_its_lexicon_lacks(tmp_path):
    """misaki alone answered ``❓`` for "Eternia" (silence). Mutation: return ``""`` instead of the
    fallback -> "Zorb" disappears; drop the ``eos`` stop -> the decode runs to ``max_steps``."""
    g2p, model = _misaki(tmp_path, _greedy([4, 5, 6, 7, 2]))
    assert g2p("zorb files.") == "zɔɹb fˈIlz."
    assert len(model.calls) == 5 and model.calls[0]["input_ids"][0][1:-1] == [
        _GRAPHEMES.index(c) for c in "zorb"]


def test_misaki_reads_known_words_without_the_model_and_product_names_first(tmp_path):
    """Mutation: skip the product lexicon -> "Eternia" goes to the model; drop the ``to`` rule ->
    ``tə`` before a vowel instead of ``tʊ``."""
    g2p, model = _misaki(tmp_path, _greedy([2]))
    assert g2p("to Eternia, read") == "tʊ " + speech_phonemize.PRODUCT_LEXICON["eternia"]["kokoro"] + ", ɹˈid"
    assert g2p("PM") == "pˌiˈɛm"
    assert model.calls == []
    # A fallback that answers nothing (end at once) still says something: the letters.
    # Mutation: drop the ``_letters`` backstop in ``word`` -> "".
    assert g2p("pm") == "pˌiˈɛm" and len(model.calls) == 1


def test_kokoro_tokens_are_its_vocabulary_ids(tmp_path):
    g2p, _model = _misaki(tmp_path, _greedy([2]))
    voice = speech_onnx_voice.KokoroVoice(tmp_path / "k.onnx", g2p=g2p, model=object(), styles={"af_heart": []})
    assert voice.tokens("fIlz.") == [1, 2, 3, 4, 6]


def test_the_voice_family_is_read_from_the_files_beside_it(tmp_path):
    """Mutation: test the voices file before the ``.onnx.json`` -> a Piper voice in a folder that
    also holds Kokoro's voices file is loaded as Kokoro."""
    voice = _piper_config(tmp_path, "en-us")
    assert speech_onnx_voice.voice_family(voice) == "piper"
    (tmp_path / speech_onnx_voice.KOKORO_VOICES).write_bytes(b"\1")
    assert speech_onnx_voice.voice_family(voice) == "piper"
    assert speech_onnx_voice.voice_family(tmp_path / "kokoro-v1.0.onnx") == "kokoro"
    assert speech_onnx_voice.voice_family(tmp_path / "elsewhere" / "x.onnx") is None
