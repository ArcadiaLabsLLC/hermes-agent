"""BERT's uncased WordPiece tokenizer, the one bge-small-en-v1.5 reads (``vocab.txt``).

Pure Python, so the bundled pack needs no ``tokenizers`` wheel. The steps are BERT's
``BasicTokenizer`` (clean, split CJK ideographs, lowercase, strip accents, split punctuation)
then ``WordpieceTokenizer`` (greedy longest match, ``##`` continuations, ``[UNK]`` for a word
with no split or over 100 characters), as in Hugging Face ``BertTokenizer`` with
``do_lower_case=True`` (bge's ``tokenizer_config.json``).
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

__layer__ = "models"

__all__ = ["WordPiece"]

_MAX_WORD_CHARS = 100
_CJK_RANGES = (
    (0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x20000, 0x2A6DF), (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F), (0x2B820, 0x2CEAF), (0xF900, 0xFAFF), (0x2F800, 0x2FA1F),
)


def _is_punctuation(char: str) -> bool:
    code = ord(char)
    if 33 <= code <= 47 or 58 <= code <= 64 or 91 <= code <= 96 or 123 <= code <= 126:
        return True
    return unicodedata.category(char).startswith("P")


def _is_cjk(code: int) -> bool:
    return any(low <= code <= high for low, high in _CJK_RANGES)


def _clean(text: str) -> str:
    out = []
    for char in text:
        code = ord(char)
        if code in (0, 0xFFFD):
            continue
        if char in "\t\n\r" or unicodedata.category(char) == "Zs":
            out.append(" ")
        elif unicodedata.category(char).startswith("C"):
            continue
        elif _is_cjk(code):
            out.append(f" {char} ")
        else:
            out.append(char)
    return "".join(out)


def _split_punctuation(word: str) -> list[str]:
    pieces: list[str] = []
    current = ""
    for char in word:
        if _is_punctuation(char):
            if current:
                pieces.append(current)
                current = ""
            pieces.append(char)
        else:
            current += char
    if current:
        pieces.append(current)
    return pieces


def basic_tokens(text: str) -> list[str]:
    """BERT's ``BasicTokenizer`` with lower-casing and accent stripping."""
    tokens: list[str] = []
    for word in _clean(text).split():
        word = "".join(c for c in unicodedata.normalize("NFD", word.lower()) if unicodedata.category(c) != "Mn")
        tokens.extend(_split_punctuation(word))
    return tokens


class WordPiece:
    """``encode(text)`` -> ``[CLS] … [SEP]`` ids, truncated to ``max_tokens``."""

    def __init__(self, vocab: dict[str, int], *, max_tokens: int = 512) -> None:
        self.vocab = vocab
        self.max_tokens = max_tokens
        self.unk, self.cls, self.sep = vocab["[UNK]"], vocab["[CLS]"], vocab["[SEP]"]
        self.pad = vocab.get("[PAD]", 0)

    @classmethod
    def from_file(cls, path: Path, *, max_tokens: int = 512) -> "WordPiece":
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        return cls({token: index for index, token in enumerate(lines)}, max_tokens=max_tokens)

    def _pieces(self, word: str) -> list[int]:
        if len(word) > _MAX_WORD_CHARS:
            return [self.unk]
        ids: list[int] = []
        start = 0
        while start < len(word):
            end = len(word)
            found = None
            while start < end:
                piece = word[start:end] if start == 0 else "##" + word[start:end]
                if piece in self.vocab:
                    found = self.vocab[piece]
                    break
                end -= 1
            if found is None:
                return [self.unk]
            ids.append(found)
            start = end
        return ids

    def encode(self, text: str) -> list[int]:
        ids: list[int] = []
        for word in basic_tokens(text):
            ids.extend(self._pieces(word))
        return [self.cls, *ids[: self.max_tokens - 2], self.sep]
