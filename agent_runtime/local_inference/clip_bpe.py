"""CLIP's byte-level BPE tokenizer (``vocab.json`` + ``merges.txt``), pure Python.

The steps are OpenAI CLIP's ``SimpleTokenizer`` as Hugging Face ``CLIPTokenizer`` runs it without
ftfy: unescape HTML, collapse whitespace, lowercase, split with CLIP's pattern, map each byte to
its printable stand-in, then merge by rank with ``</w>`` closing each word. The pattern's
``\\p{L}`` / ``\\p{N}`` classes are spelled for the standard ``re`` module (letters are
``[^\\W\\d_]``, digits ``\\d``), so no ``regex`` wheel joins the pack.
"""

from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path

__layer__ = "models"

__all__ = ["ClipBpe"]

_PATTERN = re.compile(
    r"<\|startoftext\|>|<\|endoftext\|>|'s|'t|'re|'ve|'m|'ll|'d|[^\W\d_]+|\d|(?:[^\s\w]|_)+",
    re.IGNORECASE,
)
_START, _END = "<|startoftext|>", "<|endoftext|>"


@lru_cache(maxsize=1)
def _byte_alphabet() -> dict[int, str]:
    """GPT-2's reversible byte -> printable-character table."""
    printable = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) \
        + list(range(ord("®"), ord("ÿ") + 1))
    codes = printable[:]
    extra = 0
    for byte in range(256):
        if byte not in printable:
            printable.append(byte)
            codes.append(256 + extra)
            extra += 1
    return dict(zip(printable, (chr(code) for code in codes)))


def _clean(text: str) -> str:
    return " ".join(html.unescape(html.unescape(text)).split()).lower()


class ClipBpe:
    """``encode(text)`` -> ``<|startoftext|> … <|endoftext|>`` ids, truncated to ``max_tokens``."""

    def __init__(self, vocab: dict[str, int], merges: list[tuple[str, str]], *, max_tokens: int = 77) -> None:
        self.vocab = vocab
        self.ranks = {pair: rank for rank, pair in enumerate(merges)}
        self.max_tokens = max_tokens
        self.start, self.end = vocab[_START], vocab[_END]
        self._memo: dict[str, tuple[str, ...]] = {}

    @classmethod
    def from_files(cls, vocab_path: Path, merges_path: Path, *, max_tokens: int = 77) -> ClipBpe:
        vocab = json.loads(Path(vocab_path).read_text(encoding="utf-8"))
        merges = []
        for line in Path(merges_path).read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and not line.startswith("#version"):
                merges.append((parts[0], parts[1]))
        return cls(vocab, merges, max_tokens=max_tokens)

    def _bpe(self, token: str) -> tuple[str, ...]:
        if token in self._memo:
            return self._memo[token]
        word = (*token[:-1], token[-1] + "</w>")
        while len(word) > 1:
            pairs = {(word[i], word[i + 1]) for i in range(len(word) - 1)}
            best = min(pairs, key=lambda pair: self.ranks.get(pair, float("inf")))
            if best not in self.ranks:
                break
            merged: list[str] = []
            i = 0
            while i < len(word):
                if i < len(word) - 1 and (word[i], word[i + 1]) == best:
                    merged.append(word[i] + word[i + 1])
                    i += 2
                else:
                    merged.append(word[i])
                    i += 1
            word = tuple(merged)
        if len(self._memo) < 10_000:
            self._memo[token] = word
        return word

    def encode(self, text: str) -> list[int]:
        alphabet = _byte_alphabet()
        ids: list[int] = []
        for match in _PATTERN.findall(_clean(text)):
            token = "".join(alphabet[byte] for byte in match.encode("utf-8"))
            ids.extend(self.vocab[piece] for piece in self._bpe(token) if piece in self.vocab)
        return [self.start, *ids[: self.max_tokens - 2], self.end]
