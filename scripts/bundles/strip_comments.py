"""Drop ``#`` comments from a first-party module the packager ships, keeping every line where it was.

Fork-owned (RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT). A profile with
``packaging.strip_comments: true`` (``bundled-phone``) ships its first-party ``.py`` files through
:func:`strip_comments`: comments are about a sixth of the phone bundle's compressed Python and nothing
reads them at run time. The result has the same number of lines, each statement on the line it was
on, so a traceback from the phone still points at the line in the source tree. Docstrings stay: code
reads ``__doc__`` (tool and command descriptions). A shebang and an encoding declaration on the first
two lines stay too (PEP 263 reads the declaration). A file the tokenizer cannot read, or whose
stripped text does not compile, ships unchanged.
"""

from __future__ import annotations

import io
import re
import tokenize

__all__ = ["strip_comments"]

#: PEP 263's declaration, which must survive on line 1 or 2.
_CODING = re.compile(rb"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")


def _kept(token: tokenize.TokenInfo, source_lines: list[bytes]) -> bool:
    if token.type != tokenize.COMMENT:
        return True
    row = token.start[0]
    if row > 2:
        return False
    line = source_lines[row - 1]
    return line.startswith(b"#!") if row == 1 and token.string.startswith("#!") else bool(_CODING.match(line))


def strip_comments(source: bytes, filename: str = "<bundle>") -> bytes:
    """``source`` without its comments, line for line; ``source`` itself when that cannot be done safely."""
    try:
        tokens = list(tokenize.tokenize(io.BytesIO(source).readline))
        lines = source.splitlines()
        dropped = {t.start[0] for t in tokens if not _kept(t, lines)}
        stripped = tokenize.untokenize([t for t in tokens if _kept(t, lines)])
        # Only a row that lost a comment loses its trailing blanks: a comment ends its line, so they are
        # not inside a string there; elsewhere trailing blanks may be part of a triple-quoted string.
        stripped = b"\n".join(line.rstrip() if row in dropped else line
                               for row, line in enumerate(stripped.split(b"\n"), start=1))
        if stripped.count(b"\n") != source.replace(b"\r\n", b"\n").count(b"\n"):
            return source
        compile(stripped, filename, "exec", dont_inherit=True)
    except (SyntaxError, tokenize.TokenError, ValueError, UnicodeDecodeError):
        return source
    return stripped
