"""Drop ``#`` comments from a first-party module the packager ships, keeping every line where it was.

Fork-owned (RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT). A profile with
``packaging.strip_comments: true`` (``bundled-phone``) ships its first-party ``.py`` files through
:func:`strip_comments`: comments are about a sixth of the phone bundle's compressed Python and nothing
reads them at run time. The result has the same number of lines, each statement on the line it was
on, so a traceback from the phone still points at the line in the source tree. A shebang and an
encoding declaration on the first two lines stay too (PEP 263 reads the declaration). A file the
tokenizer cannot read, or whose stripped text does not compile, ships unchanged.

``packaging.strip_function_docstrings: true`` also empties every FUNCTION and method docstring
(:func:`strip_function_docstrings`), line for line, to ``""``. Audited 2026-11-19: no first-party code
reads a function's ``__doc__`` for its content (the reads copy one wrapper's ``__doc__`` onto
another; tool and RPC descriptions are written out, never taken from a docstring). Module and class
docstrings stay: argparse ``description=__doc__`` reads a module's, pydantic's schema a class's.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize

__all__ = ["strip_comments", "strip_function_docstrings"]

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


def _function_docstring_spans(tree: ast.AST) -> list[tuple[int, int, int, int]]:
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                spans.append((first.lineno, first.col_offset, first.end_lineno, first.end_col_offset))
    return spans


def strip_function_docstrings(source: bytes, filename: str = "<bundle>") -> bytes:
    """``source`` with every function docstring emptied to ``""``, line for line; ``source`` itself when
    that cannot be done safely (a statement after the docstring on its last line, a file that does not
    parse or no longer compiles)."""
    try:
        lines = source.split(b"\n")
        for row, col, end_row, end_col in sorted(_function_docstring_spans(ast.parse(source)), reverse=True):
            tail = lines[end_row - 1][end_col:]
            if tail.strip():  # `"""doc"""; x = 1` — leave the line alone
                continue
            first = lines[row - 1]
            lines[row - 1] = first[:col] + b'""' + (b"\r" if first.endswith(b"\r") else b"")
            for index in range(row, end_row):  # col offsets are UTF-8 byte offsets, as these lines are
                lines[index] = b"\r" if lines[index].endswith(b"\r") else b""
        stripped = b"\n".join(lines)
        compile(stripped, filename, "exec", dont_inherit=True)
    except (SyntaxError, ValueError, UnicodeDecodeError):
        return source
    return stripped
