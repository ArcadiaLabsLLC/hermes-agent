"""The pure halves of the verbs, as Eternia's ``file_tree_replies.dart`` writes them."""

from __future__ import annotations

__layer__ = "models"

from agent_runtime.project_files.patterns import Deadline, LinePattern, check_pattern
from agent_runtime.project_files.rules import (
    BINARY_PROBE_BYTES, LINE_CODE_POINTS, READ_PAGE_CODE_POINTS, ProjectFileRefusal,
)

__all__ = ["check_offset", "check_pattern", "decode_text", "grep_lines", "looks_binary", "page",
           "read_reply"]


def looks_binary(head: bytes) -> bool:
    """Whether a file's first bytes mark it binary (a NUL within the probe)."""

    return b"\x00" in head[:BINARY_PROBE_BYTES]


def decode_text(data: bytes, path: str) -> str:
    """``data`` as UTF-8 text, refused ``not_text`` otherwise — never replaced."""

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ProjectFileRefusal("not_text", f"the file is not UTF-8 text: {path}") from None


def check_offset(offset: int, length: int) -> None:
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or offset > length:
        raise ProjectFileRefusal("bad_argument", f"offset must be 0-{length}, not {offset!r}")


def read_reply(path: str, size: int, text: str, offset: int) -> dict:
    """The ``read`` reply: one page of ``text`` from ``offset`` code points."""

    check_offset(offset, len(text))
    end = min(offset + READ_PAGE_CODE_POINTS, len(text))
    reply = {"path": path, "size": size, "chars": len(text), "offset": offset,
             "content": text[offset:end]}
    if end < len(text):
        reply["next"] = end
    return reply


def grep_lines(path: str, text: str, pattern: LinePattern, deadline: Deadline | None = None,
               context: int = 0) -> list[dict]:
    """Every line of ``text`` that ``pattern`` matches, as matches of ``path``, asking ``deadline`` per line.

    With ``context`` (an agent's ``search_files`` argument; the spec's ``grep`` verb gives none), each
    match also carries up to that many lines ``before`` and ``after`` it, as ``{line, text}``."""

    lines = [line.removesuffix("\r") for line in text.split("\n")]
    # A final newline ends the last line; it starts no empty one that context could show. MUTATION: bound
    # ``after`` by len(lines) (test_phone_file_tools: test_search_takes_every_desktop_argument_over_the_reader).
    last = len(lines) - 1 if text.endswith("\n") else len(lines)
    matches = []
    for index, line in enumerate(lines):
        if deadline is not None:
            deadline.check()
        if pattern.matches(line):
            match = {"path": path, "line": index + 1, "text": line[:LINE_CODE_POINTS]}
            if context > 0:
                # MUTATION: drop the before half and a desktop context=1 call loses the line above
                # (test_phone_file_tools: test_search_takes_every_desktop_argument_over_the_reader).
                match["before"] = _around(lines, max(0, index - context), index)
                match["after"] = _around(lines, index + 1, min(last, index + 1 + context))
            matches.append(match)
    return matches


def _around(lines: list[str], start: int, end: int) -> list[dict]:
    return [{"line": at + 1, "text": lines[at][:LINE_CODE_POINTS]} for at in range(start, end)]


def page(header: dict, field: str, items: list[dict], offset: int, most: int) -> dict:
    """One counted page of ``items`` under ``field``, from ``offset``, at most ``most``."""

    check_offset(offset, len(items))
    end = min(offset + most, len(items))
    reply = {**header, field: items[offset:end], "total": len(items), "offset": offset}
    if end < len(items):
        reply["next"] = end
    return reply
