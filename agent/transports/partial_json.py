"""Partial JSON the way the ``anthropic`` SDK reads a streamed tool input — without ``jiter``.

While a ``tool_use`` block streams, the SDK re-parses the accumulated ``partial_json``
after every delta with ``jiter.from_json(buf, partial_mode=True)`` and stores the result
as the block's ``input``; the final message's ``input`` is that parse of the whole
buffer. ``jiter`` is Rust, which a phone cannot load, so the SDK-free Anthropic client
(:mod:`agent.transports.httpx_anthropic`) parses here instead, with ``jiter``'s partial
rules (measured against it in ``tests/agent/transports/test_partial_json.py``):

* a scalar cut off by the end of input is dropped, and so is its key; a container cut
  off keeps what it has (``{"a": [1, "x`` -> ``{"a": [1]}``);
* where a ``,`` or a closer should follow a complete value, anything else ends the parse
  as the end of input would (``{"a": 1 "b": 2}`` -> ``{"a": 1}``);
* an invalid value raises :class:`ValueError` with ``jiter``'s message (``expected value
  at line 1 column 11``) — the loop's retry path for a malformed fine-grained tool stream
  (``agent.api_error_summary.PROVIDER_STREAM_PARSE_MARKERS``) keys on those words.
"""

from __future__ import annotations

from typing import Any

__all__ = ["parse_partial_json"]

_WHITESPACE = " \t\n\r"
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_LITERALS = {"t": ("true", True), "f": ("false", False), "n": ("null", None)}
_DIGITS = "0123456789"


class _Cut(Exception):
    """The input ended inside a scalar; ``what`` names it for a top-level error."""

    def __init__(self, what: str) -> None:
        super().__init__(what)
        self.what = what


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        #: Set once the parse has ended early (end of input, or a stray character after a value).
        self.stopped = False

    # ── positions and errors ─────────────────────────────────────────────────

    def _line_start(self, index: int) -> int:
        return self.text.rfind("\n", 0, index) + 1

    def error(self, message: str, index: int | None = None) -> ValueError:
        """``jiter``'s ``<message> at line L column C``: C is 1-based at a character, and the
        count of characters read on that line at the end of input."""
        at = self.pos if index is None else index
        line = self.text.count("\n", 0, at) + 1
        column = at - self._line_start(at) + (1 if at < len(self.text) else 0)
        return ValueError(f"{message} at line {line} column {column}")

    def skip_ws(self) -> str | None:
        while self.pos < len(self.text) and self.text[self.pos] in _WHITESPACE:
            self.pos += 1
        return self.text[self.pos] if self.pos < len(self.text) else None

    # ── values ───────────────────────────────────────────────────────────────

    def value(self) -> Any:
        char = self.skip_ws()
        if char is None:
            raise _Cut("a value")
        reader = _READERS.get(char)
        if reader is None:
            reader = _Parser.number if char == "-" or char in _DIGITS else None
        if reader is None:
            raise self.error("expected value")
        return reader(self)

    def literal(self) -> Any:
        word, result = _LITERALS[self.text[self.pos]]
        for offset, expected in enumerate(word):
            index = self.pos + offset
            if index >= len(self.text):
                raise _Cut("a value")
            if self.text[index] != expected:
                raise self.error("expected ident", index)
        self.pos += len(word)
        return result

    def number(self) -> Any:
        start = self.pos
        if self.text[self.pos] == "-":
            self.pos += 1
        self._digits(leading=True)
        is_float = False
        if self._peek() == ".":
            self.pos += 1
            self._digits(leading=False)
            is_float = True
        if self._peek() in ("e", "E"):
            self.pos += 1
            if self._peek() in ("+", "-"):
                self.pos += 1
            self._digits(leading=False)
            is_float = True
        text = self.text[start:self.pos]
        return float(text) if is_float else int(text)

    def _peek(self) -> str | None:
        return self.text[self.pos] if self.pos < len(self.text) else None

    def _digits(self, *, leading: bool) -> None:
        first = self._peek()
        if first is None:
            raise _Cut("a value")
        if first not in _DIGITS:
            raise self.error("invalid number")
        self.pos += 1
        if leading and first == "0":
            if self._peek() is not None and self._peek() in _DIGITS:
                raise self.error("invalid number")
            return
        while self._peek() is not None and self._peek() in _DIGITS:
            self.pos += 1

    def string(self) -> str:
        self.pos += 1  # the opening quote
        out: list[str] = []
        while True:
            char = self._peek()
            if char is None:
                raise _Cut("a string")
            self.pos += 1
            if char == '"':
                return "".join(out)
            if char == "\\":
                out.append(self._escape())
            elif char < " ":
                raise self.error("control character (\\u0000-\\u001F) found while parsing a string", self.pos - 1)
            else:
                out.append(char)

    def _escape(self) -> str:
        char = self._peek()
        if char is None:
            raise _Cut("a string")
        self.pos += 1
        if char in _ESCAPES:
            return _ESCAPES[char]
        if char != "u":
            raise self.error("invalid escape", self.pos - 1)
        code = self._hex4()
        if not 0xD800 <= code <= 0xDBFF:
            return chr(code)
        # A leading surrogate must be followed by its trailing ``\\uXXXX``.
        if self.text[self.pos:self.pos + 2] != "\\u":
            if self.pos + 2 > len(self.text) and "\\u".startswith(self.text[self.pos:]):
                raise _Cut("a string")
            raise self.error("unexpected end of hex escape")
        self.pos += 2
        low = self._hex4()
        return chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00))

    def _hex4(self) -> int:
        for offset in range(4):
            index = self.pos + offset
            if index >= len(self.text):
                raise _Cut("a string")
            if self.text[index] not in "0123456789abcdefABCDEF":
                raise self.error("invalid escape", index)
        code = int(self.text[self.pos:self.pos + 4], 16)
        self.pos += 4
        return code

    # ── containers ───────────────────────────────────────────────────────────

    def _member(self, read: Any) -> bool:
        """Read one member (``read`` stores it); False when the parse ended in or after it."""
        try:
            read()
        except _Cut:
            self.stopped = True
            return False
        return not self.stopped

    def _after_member(self, closer: str) -> bool:
        """After a complete member: True when another follows; False when the container closed
        or the parse ended. A comma straight before the closer is ``jiter``'s trailing-comma error."""
        char = self.skip_ws()
        if char == closer:
            self.pos += 1
            return False
        if char != ",":
            self.stopped = True  # end of input, or a stray character: the parse ends here
            return False
        self.pos += 1
        after = self.skip_ws()
        if after == closer:
            raise self.error("trailing comma")
        if after is None:
            self.stopped = True
            return False
        return True

    def array(self) -> list:
        self.pos += 1
        items: list = []
        char = self.skip_ws()
        if char == "]":
            self.pos += 1
            return items
        if char is None:
            self.stopped = True
            return items
        while self._member(lambda: items.append(self.value())) and self._after_member("]"):
            pass
        return items

    def object(self) -> dict:
        self.pos += 1
        members: dict = {}
        char = self.skip_ws()
        if char == "}":
            self.pos += 1
            return members
        if char is None:
            self.stopped = True
            return members
        while self._member(lambda: self._key_value(members)) and self._after_member("}"):
            pass
        return members

    def _key_value(self, members: dict) -> None:
        char = self.skip_ws()
        if char is None:
            raise _Cut("a string")
        if char != '"':
            raise self.error("key must be a string")
        key = self.string()
        char = self.skip_ws()
        if char is None:
            raise _Cut("a value")
        if char != ":":
            raise self.error("expected `:`")
        self.pos += 1
        value = self.value()
        members[key] = value


_READERS = {"{": _Parser.object, "[": _Parser.array, '"': _Parser.string,
            "t": _Parser.literal, "f": _Parser.literal, "n": _Parser.literal}


def parse_partial_json(text: str) -> Any:
    """``jiter.from_json(text, partial_mode=True)`` in pure Python (see the module docstring)."""
    parser = _Parser(text)
    try:
        return parser.value()
    except _Cut as cut:
        raise parser.error(f"EOF while parsing {cut.what}", len(text)) from None
