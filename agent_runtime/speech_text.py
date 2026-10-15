"""Text normalization for the speech pack's phonemizers: sentences, numbers and clock times as words.

Fork-owned (bundled desktop, GPL-free speech pack). Both phonemizers in
:mod:`agent_runtime.speech_phonemize` read words, not digits, and the pack ships
no ``num2words`` (LGPL-2.1), so digits are spelled here, English only (owner
ruling 1: English first). Stdlib only.
"""

from __future__ import annotations

import re

__layer__ = "stores"

__all__ = ["number_words", "sentences", "spell_numbers"]

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALES = ((10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand"))
_ORDINAL_ENDS = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
                 "nine": "ninth", "twelve": "twelfth"}

#: ``3:45``, ``3:45 PM``, ``12:05am``.
_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})(?:\s*([AaPp])\.?\s*[Mm]\.?\b)?")
_ORDINAL = re.compile(r"\b(\d+)(st|nd|rd|th)\b", re.I)
_DECIMAL = re.compile(r"(?<![\d.])(\d+)\.(\d+)\b")
_INTEGER = re.compile(r"\d[\d,]*")
_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"”')\]]*\s+")


def _below_thousand(n: int) -> list[str]:
    words: list[str] = []
    if n >= 100:
        words += [_ONES[n // 100], "hundred"]
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else ""))
    elif n or not words:
        words.append(_ONES[n])
    return words


def number_words(n: int) -> str:
    """``1234`` -> ``one thousand two hundred thirty-four`` (no "and", as US English says it)."""
    if n < 0:
        return "minus " + number_words(-n)
    words: list[str] = []
    for scale, name in _SCALES:
        if n >= scale:
            words += _below_thousand(n // scale) + [name]
            n %= scale
    if n or not words:
        words += _below_thousand(n)
    return " ".join(words)


def _ordinal(n: int) -> str:
    words = number_words(n)
    head, _, last = words.rpartition(" ")
    last_part = last.rpartition("-")
    end = last_part[2]
    if end in _ORDINAL_ENDS:
        end = _ORDINAL_ENDS[end]
    elif end.endswith("y"):
        end = end[:-1] + "ieth"
    else:
        end += "th"
    last = last_part[0] + last_part[1] + end
    return f"{head} {last}".strip()


def _clock(match: re.Match) -> str:
    hour, minute, half = int(match.group(1)), int(match.group(2)), match.group(3)
    spoken = number_words(hour)
    if minute == 0:
        spoken += "" if half else " o'clock"
    elif minute < 10:
        spoken += " oh " + number_words(minute)
    else:
        spoken += " " + number_words(minute)
    return spoken + (f" {half.upper()} M" if half else "")


def _year_or_number(match: re.Match) -> str:
    digits = match.group(0).rstrip(",")
    tail = match.group(0)[len(digits):]
    value = int(digits.replace(",", ""))
    if "," not in digits and len(digits) == 4 and 1100 <= value <= 2099 and value % 1000 >= 10:
        # A four-digit year reads in pairs: 1999 -> nineteen ninety-nine; 2026 -> twenty twenty-six.
        high, low = divmod(value, 100)
        low_words = "hundred" if low == 0 else ("oh " + number_words(low) if low < 10 else number_words(low))
        return f"{number_words(high)} {low_words}{tail}"
    return number_words(value) + tail


def spell_numbers(text: str) -> str:
    """Clock times, ordinals, decimals, then whole numbers, as English words."""
    text = _CLOCK.sub(_clock, text)
    text = _ORDINAL.sub(lambda m: _ordinal(int(m.group(1))), text)
    text = _DECIMAL.sub(lambda m: f"{number_words(int(m.group(1)))} point "
                        + " ".join(_ONES[int(d)] for d in m.group(2)), text)
    text = re.sub(r"(\d)%", r"\1 percent", text)
    return _INTEGER.sub(_year_or_number, text)


def sentences(text: str) -> list[str]:
    """Split on sentence-final punctuation followed by space; blank pieces are dropped."""
    return [piece.strip() for piece in _SENTENCE_END.split(text.strip()) if piece.strip()]
