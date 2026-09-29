"""The speech pack's phonemizers, on onnxruntime: no espeak-ng, no torch, no GPL code.

Fork-owned (bundled desktop; owner ruling 2026-09-28, second sitting, item 2 —
launcher ``docs/embedded_hermes/planned/GPL_FREE_TTS_OPTIONS_2026-09-28.md``).
Each phonemizer is a downloadable ARTIFACT (an ``.onnx`` + a ``.json``) the
Launcher places next to the voice it serves; this module is the code that runs
it. The artifacts are produced by ``scripts/phonemizer_openphonemizer_onnx.py`` and
``scripts/phonemizer_misaki_g2p_onnx.py``.

* :class:`OpenPhonemizer` — espeak-style IPA for Piper voices, from
  OpenPhonemizer (BSD-3-Clause-Clear): its word dictionary first, then its
  forward transformer for any other word. The word split, dictionary order and
  acronym expansion follow DeepPhonemizer's ``Phonemizer`` (MIT).
* :class:`MisakiG2P` — misaki phonemes for Kokoro: misaki's gold and silver
  lexicons, then misaki's neural fallback (``PeterReid/graphemes_to_phonemes_en_us``),
  so no word is ever dropped. The lookup below (stress, ``-s``/``-ed``/``-ing``
  stems, the/to/a) is adapted from misaki's ``en.Lexicon`` (Apache-2.0,
  Copyright hexgrad) without its spaCy part-of-speech tags, which the pack does
  not ship: a heteronym reads its DEFAULT entry.

Both consult :data:`PRODUCT_LEXICON` first, so product names are said the way
the product says them.
"""

from __future__ import annotations

import json
import re
import unicodedata
from itertools import zip_longest
from pathlib import Path
from typing import Any

from agent_runtime.speech_text import spell_numbers

__layer__ = "stores"

__all__ = ["MisakiG2P", "OnnxModel", "OpenPhonemizer", "PHONEMIZER_ARTIFACTS", "PRODUCT_LEXICON", "artifact_files",
           "rp_from_us"]

#: The artifact each voice family reads, as ``(onnx, json)`` names next to the voice.
PHONEMIZER_ARTIFACTS = {
    "piper": ("openphonemizer-en_us.onnx", "openphonemizer-en_us.json"),
    "kokoro": ("misaki-en_us-g2p.onnx", "misaki-en_us-g2p.json"),
}

#: Product names in each family's symbol set: espeak IPA (Piper) and misaki (Kokoro).
PRODUCT_LEXICON: dict[str, dict[str, str]] = {
    "eternia": {"piper": "ɪtˈɜːniə", "kokoro": "ətˈɜɹniə"},
    "hermes": {"piper": "hˈɜːmiːz", "kokoro": "hˈɜɹmiz"},
    "arcadia": {"piper": "ɑːɹkˈeɪdiə", "kokoro": "ɑɹkˈAdiə"},
}


def artifact_files(family: str, voice: Path) -> tuple[Path, Path]:
    onnx, sidecar = PHONEMIZER_ARTIFACTS[family]
    return voice.parent / onnx, voice.parent / sidecar


class OnnxModel:
    """One onnxruntime session on the CPU. Feeds are plain lists (ints -> int64, floats -> float32)
    or arrays; :meth:`run` answers the first output as an array, :meth:`rows` as nested lists — the
    phonemizers read only that, so they never import numpy themselves."""

    def __init__(self, path: Path) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.log_severity_level = 3
        self._session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])

    def run(self, feeds: dict[str, Any]) -> Any:
        import numpy as np

        arrays = {}
        for name, value in feeds.items():
            array = np.asarray(value)
            arrays[name] = array.astype(np.int64 if array.dtype.kind in "iu" else np.float32, copy=False)
        return self._session.run(None, arrays)[0]

    def rows(self, feeds: dict[str, Any]) -> list:
        return self.run(feeds).tolist()


def _argmax(row: list[float]) -> int:
    return max(range(len(row)), key=row.__getitem__)


# ── OpenPhonemizer (Piper) ──────────────────────────────────────────────────

_DP_PUNCTUATION = "().,:?!/–"

#: A capital letter standing alone (an initialism after the acronym split: ``PM`` -> ``P-M``) is
#: said by its name. The dictionary has no single letters and the model reads them as sounds.
#: ``A`` is left out: alone it is the article far more often than the letter.
_LETTER_NAMES = dict(zip("BCDEFGHIJKLMNOPQRSTUVWXYZ", (
    "bˈiː sˈiː dˈiː ˈiː ˈɛf dʒˈiː ˈeɪtʃ ˈaɪ dʒˈeɪ kˈeɪ ˈɛl ˈɛm ˈɛn ˈoʊ pˈiː kjˈuː ˈɑːɹ ˈɛs tˈiː jˈuː vˈiː "
    "dˈʌbəljuː ˈɛks wˈaɪ zˈiː").split()))


class OpenPhonemizer:
    """``text -> espeak-style IPA``; words, spaces and punctuation keep their order."""

    def __init__(self, onnx_path: Path, json_path: Path, *, model: Any = None) -> None:
        meta = json.loads(Path(json_path).read_text(encoding="utf-8"))
        self._model = model or OnnxModel(onnx_path)
        self._text = meta["text_tokens"]
        self._phonemes = {int(i): t for i, t in meta["phoneme_tokens"].items()}
        self._repeats = int(meta["char_repeats"])
        self._start, self._end = int(meta["start_index"]), int(meta["end_index"])
        self._special = {self._phonemes.get(0), self._phonemes.get(self._start), self._phonemes.get(self._end)}
        self._dictionary: dict[str, str] = meta["dictionary"]
        self._punct = set(_DP_PUNCTUATION + "- ")
        self._split = re.compile(f"([{re.escape(_DP_PUNCTUATION)} ])")

    def __call__(self, text: str) -> str:
        text = spell_numbers(text).replace(" .", ".").replace(".", " .")
        cleaned = "".join(c for c in text if c.isalnum() or c in self._punct)
        return "".join(self._word(piece) for piece in self._split.split(cleaned) if piece)

    def _entry(self, word: str) -> str | None:
        if word in self._punct:
            return word
        if word in _LETTER_NAMES:
            return _LETTER_NAMES[word]
        product = PRODUCT_LEXICON.get(word.lower())
        if product is not None:
            return product["piper"]
        for form in (word, word.lower(), word.title()):
            if form in self._dictionary:
                return self._dictionary[form]
        return None

    def _word(self, word: str) -> str:
        found = self._entry(word)
        if found is not None:
            return found
        parts = re.split(r"([-])", _expand_acronym(word))
        if len(parts) <= 1:
            return self._predict(word)
        return "".join(self._entry(part) or self._predict(part) for part in parts if part)

    def _predict(self, word: str) -> str:
        ids = [self._text[c] for c in word.lower() for _ in range(self._repeats) if c in self._text]
        if not ids:
            return ""
        best = [_argmax(row) for row in self._model.rows({"text": [[self._start, *ids, self._end]]})[0]]
        out: list[str] = []
        previous = None
        for token in best:
            if token == 0:
                continue
            if token != previous:
                if token == self._end:
                    break
                symbol = self._phonemes.get(token)
                if symbol not in self._special:
                    out.append(symbol)
            previous = token
        return "".join(out)


#: US -> British espeak IPA, in order (longest first). OpenPhonemizer answers espeak's ``en-us``;
#: a voice trained on espeak's ``en`` (``ljspeech``, ``kristin``, ``norman``: their ``.onnx.json``
#: ``espeak.voice``) reads ``ɑː`` as the vowel of "dark", so an unmapped "fox" (``fˈɑːks``) is heard as
#: "farks". Rhotic endings go (``ɚ`` -> ``ə``, a vowel's ``ɹ`` before a consonant or a pause), and the
#: flap is ``t``. Lossy by nature: ``ɑː`` not before ``ɹ`` is taken as the "lot" vowel (``ɒ``), so
#: "father" comes out with it. (U+E000 holds the "dark" vowel past the ``ɑː`` rule.)
_US_VOWEL = "aeiouæɑɒɔəɛɜɪʊʌ"
_NOT_BEFORE_VOWEL = f"(?![ˈˌ]?[{_US_VOWEL}])"
_RP_FROM_US = tuple((re.compile(us), rp) for us, rp in (
    # A vowel's ɹ goes only where British English drops it: not before a vowel ("very" keeps it).
    ("ɑːɹ" + _NOT_BEFORE_VOWEL, "\ue000"), ("[ɔo]ːɹ" + _NOT_BEFORE_VOWEL, "ɔː"), ("ɜːɹ" + _NOT_BEFORE_VOWEL, "ɜː"),
    ("ɪɹ" + _NOT_BEFORE_VOWEL, "ɪə"), ("ɛɹ" + _NOT_BEFORE_VOWEL, "eə"), ("ʊɹ" + _NOT_BEFORE_VOWEL, "ʊə"),
    ("ɑː", "ɒ"), ("oʊ", "əʊ"), ("ɝ", "ɜː"), ("ɚ", "ə"), ("ɾ", "t"), ("ᵻ", "ɪ"), ("\ue000", "ɑː"),
    (f"(?<=[ːəɪʊaeɛæʌɒ])ɹ{_NOT_BEFORE_VOWEL}", "")))


def rp_from_us(ipa: str) -> str:
    """espeak ``en-us`` IPA as espeak ``en`` would write it (see :data:`_RP_FROM_US`)."""
    for us, rp in _RP_FROM_US:
        ipa = us.sub(rp, ipa)
    return ipa


def _expand_acronym(word: str) -> str:
    """``DIY`` -> ``D-I-Y`` (DeepPhonemizer's rule: a hyphen before every inner capital)."""
    pieces = []
    for sub in word.split("-"):
        chars = []
        for a, b in zip_longest(sub, sub[1:]):
            chars.append(a)
            if b is not None and b.isupper():
                chars.append("-")
        pieces.append("".join(chars))
    return "-".join(pieces)


# ── misaki (Kokoro) ─────────────────────────────────────────────────────────

_PRIMARY, _SECONDARY = "ˈ", "ˌ"
_VOWELS = frozenset("AIOQWYaiuæɑɒɔəɛɜɪʊʌᵻ")
_US_TAUS = frozenset("AIOWYiuæɑəɛɪɹʊʌ")
_PUNCTS = frozenset(';:,.!?—…"“”()')
_TOKEN = re.compile(r"[A-Za-z][A-Za-z'’]*|[^\sA-Za-z]")


def _restress(ps: str) -> str:
    ips = list(enumerate(ps))
    moves = {}
    for i, p in ips:
        if p in _PRIMARY + _SECONDARY:
            vowel = next((j for j, v in ips[i:] if v in _VOWELS), None)
            if vowel is not None:
                moves[i] = vowel - 0.5
    return "".join(p for _, p in sorted((moves.get(i, i), p) for i, p in ips))


def _apply_stress(ps: str, stress: float | None) -> str:
    """misaki's ``apply_stress``: ``None`` leaves the entry, lower values demote, higher promote."""
    has_stress = _PRIMARY in ps or _SECONDARY in ps
    if stress is None:
        return ps
    if stress < -1:
        return ps.replace(_PRIMARY, "").replace(_SECONDARY, "")
    if stress == -1 or (stress in (0, -0.5) and _PRIMARY in ps):
        return ps.replace(_SECONDARY, "").replace(_PRIMARY, _SECONDARY)
    if stress in (0, 0.5, 1) and not has_stress:
        return ps if not any(v in ps for v in _VOWELS) else _restress(_SECONDARY + ps)
    if stress >= 1 and _PRIMARY not in ps and _SECONDARY in ps:
        return ps.replace(_SECONDARY, _PRIMARY)
    if stress > 1 and not has_stress:
        return ps if not any(v in ps for v in _VOWELS) else _restress(_PRIMARY + ps)
    return ps


class MisakiG2P:
    """``text -> misaki phonemes`` for Kokoro; an unknown word goes to the neural fallback."""

    def __init__(self, onnx_path: Path, json_path: Path, *, model: Any = None) -> None:
        meta = json.loads(Path(json_path).read_text(encoding="utf-8"))
        self._model = model or OnnxModel(onnx_path)
        self._graphemes = {g: i for i, g in enumerate(meta["graphemes"])}
        self._phoneme_chars = meta["phonemes"]
        self._ids = (int(meta["start_id"]), int(meta["bos_id"]), int(meta["eos_id"]), int(meta["unknown_id"]))
        self._max_steps = int(meta["max_steps"])
        self.golds = _grow(meta["gold"])
        self.silvers = _grow(meta["silver"])
        self.vocab: dict[str, int] = meta["kokoro_vocab"]

    def __call__(self, text: str) -> str:
        text = spell_numbers(unicodedata.normalize("NFKC", text))
        tokens = _TOKEN.findall(text)
        out: list[str] = []
        for index, token in enumerate(tokens):
            if token in _PUNCTS:
                out.append(token)
                continue
            if not token[0].isalpha():
                continue
            ps = self.word(token.replace("’", "'"), _next_word(tokens, index))
            if out and out[-1] not in "(“\"":
                out.append(" ")
            out.append(ps)
        return "".join(out).strip()

    def word(self, word: str, following: str | None = None) -> str:
        product = PRODUCT_LEXICON.get(word.lower())
        if product is not None:
            return product["kokoro"]
        special = self._special_case(word, following)
        if special is not None:
            return special
        stress = None if word == word.lower() else (2 if word == word.upper() else 0.5)
        found = self._lexical(word, stress)
        if found is None and word != word.lower():
            found = self._lexical(word.lower(), stress)
        if found is not None:
            return found
        # The model can answer nothing (end at once); spelling the word beats saying nothing.
        return self._fallback(word) or self._letters(word) or ""

    def _special_case(self, word: str, following: str | None) -> str | None:
        """misaki's function words that depend on the next word (never their all-capitals form)."""
        vowel_next = None if following is None else following[:1].lower() in "aeiou"
        say = _SPECIAL_WORDS.get(word if word in ("a", "A", "I") else word.lower())
        if say is None or (word == word.upper() and len(word) > 1):
            return None
        return say(self, vowel_next)

    def _lexical(self, word: str, stress: float | None) -> str | None:
        if self._known(word):
            return self._lookup(word, stress)
        if word.endswith("'") and self._known(word[:-1]):
            return self._lookup(word[:-1], stress)
        for stem in (self._stem_s, self._stem_ed, self._stem_ing):
            found = stem(word, stress)
            if found is not None:
                return found
        return None

    def _known(self, word: str) -> bool:
        if word in self.golds or word in self.silvers:
            return True
        if not word.replace("'", "").isalpha() or not word.isascii():
            return False
        # misaki's last clause: an initialism (all capitals after the first) is known — by its letters.
        return len(word) == 1 or (word == word.upper() and word.lower() in self.golds) or word[1:] == word[1:].upper()

    def _lookup(self, word: str, stress: float | None) -> str | None:
        proper = False
        if word == word.upper() and word not in self.golds:
            word, proper = word.lower(), True
        ps = self.golds.get(word)
        if ps is None and not proper:
            ps = self.silvers.get(word)
        if isinstance(ps, dict):
            ps = ps.get("DEFAULT")
        if ps is None or (proper and _PRIMARY not in ps):
            return self._letters(word)
        return _apply_stress(ps, stress)

    def _letters(self, word: str) -> str | None:
        ps = [self.golds.get(c.upper()) for c in word if c.isalpha()]
        if not ps or None in ps:
            return None
        head, mark, tail = _apply_stress("".join(ps), 0).rpartition(_SECONDARY)
        return f"{head}{_PRIMARY}{tail}" if mark else tail

    def _stem_s(self, word: str, stress: float | None) -> str | None:
        if len(word) < 3 or not word.endswith("s"):
            return None
        if not word.endswith("ss") and self._known(word[:-1]):
            stem = word[:-1]
        elif (word.endswith("'s") or (len(word) > 4 and word.endswith("es") and not word.endswith("ies"))) \
                and self._known(word[:-2]):
            stem = word[:-2]
        elif len(word) > 4 and word.endswith("ies") and self._known(word[:-3] + "y"):
            stem = word[:-3] + "y"
        else:
            return None
        ps = self._lookup(stem, stress)
        if not ps:
            return None
        return ps + ("s" if ps[-1] in "ptkfθ" else "ᵻz" if ps[-1] in "szʃʒʧʤ" else "z")

    def _stem_ed(self, word: str, stress: float | None) -> str | None:
        if len(word) < 4 or not word.endswith("d"):
            return None
        if not word.endswith("dd") and self._known(word[:-1]):
            stem = word[:-1]
        elif len(word) > 4 and word.endswith("ed") and not word.endswith("eed") and self._known(word[:-2]):
            stem = word[:-2]
        else:
            return None
        ps = self._lookup(stem, stress)
        if not ps:
            return None
        if ps[-1] == "t":
            return ps[:-1] + "ɾᵻd" if len(ps) > 1 and ps[-2] in _US_TAUS else ps + "ᵻd"
        return ps + next((tail for ends, tail in _ED_TAILS if ps[-1] in ends), "d")

    def _stem_ing(self, word: str, stress: float | None) -> str | None:
        if len(word) < 5 or not word.endswith("ing"):
            return None
        if len(word) > 5 and self._known(word[:-3]):
            stem = word[:-3]
        elif self._known(word[:-3] + "e"):
            stem = word[:-3] + "e"
        elif len(word) > 5 and re.search(r"([bcdgklmnprstvxz])\1ing$|cking$", word) and self._known(word[:-4]):
            stem = word[:-4]
        else:
            return None
        ps = self._lookup(stem, 0.5 if stress is None else stress)
        if not ps:
            return None
        return ps[:-1] + "ɾɪŋ" if len(ps) > 1 and ps[-1] == "t" and ps[-2] in _US_TAUS else ps + "ɪŋ"

    def _fallback(self, word: str) -> str:
        """misaki's ``FallbackNetwork``: greedy decode, one full forward per step (the model is 0.75 M)."""
        start, bos, eos, unknown = self._ids
        ids = [[bos, *(self._graphemes.get(c, unknown) for c in word), eos]]
        out = [start]
        for _ in range(self._max_steps - 1):
            logits = self._model.rows({"input_ids": ids, "decoder_input_ids": [out]})
            out.append(_argmax(logits[0][-1]))
            if out[-1] == eos:
                break
        return "".join(self._phoneme_chars[t] for t in out if t > 3 and t < len(self._phoneme_chars))


#: misaki's ``-ed``: voiceless endings take ``t``, ``d`` takes ``ᵻd``, the rest ``d`` (``t`` is its own case).
_ED_TAILS = (("pkfθʃsʧ", "t"), ("d", "ᵻd"))

#: misaki's context words: ``vowel_next`` is None at a pause, else whether the next word starts with a vowel.
_SPECIAL_WORDS = {
    "the": lambda g2p, vowel_next: "ði" if vowel_next else "ðə",
    "to": lambda g2p, vowel_next: {None: g2p.golds["to"], False: "tə", True: "tʊ"}[vowel_next],
    "an": lambda g2p, vowel_next: "ɐn",
    "a": lambda g2p, vowel_next: f"{_PRIMARY}A" if vowel_next is None else "ɐ",
    "A": lambda g2p, vowel_next: f"{_PRIMARY}A" if vowel_next is None else "ɐ",
    "I": lambda g2p, vowel_next: f"{_SECONDARY}I",
}


def _grow(entries: dict) -> dict:
    """misaki's ``grow_dictionary``: every lower-case entry also answers capitalized, and back."""
    grown = {}
    for key, value in entries.items():
        if len(key) < 2:
            continue
        if key == key.lower():
            if key != key.capitalize():
                grown[key.capitalize()] = value
        elif key == key.lower().capitalize():
            grown[key.lower()] = value
    return {**grown, **entries}


def _next_word(tokens: list[str], index: int) -> str | None:
    for token in tokens[index + 1:]:
        if token[0].isalpha():
            return token
        if token in _PUNCTS:
            return None
    return None
