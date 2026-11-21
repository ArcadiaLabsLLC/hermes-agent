"""The pure halves of the verbs, as Eternia's ``file_tree_replies.dart`` writes them."""

from __future__ import annotations

from agent_runtime.project_files.rules import (
    BINARY_PROBE_BYTES, LINE_CODE_POINTS, MAX_PATTERN, MIN_PATTERN, READ_PAGE_CODE_POINTS,
    ProjectFileRefusal,
)


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


def check_pattern(pattern: str) -> None:
    if not isinstance(pattern, str) or not MIN_PATTERN <= len(pattern) <= MAX_PATTERN:
        raise ProjectFileRefusal("bad_argument",
                                 f"pattern must be {MIN_PATTERN}-{MAX_PATTERN} characters")


def read_reply(path: str, size: int, text: str, offset: int) -> dict:
    """The ``read`` reply: one page of ``text`` from ``offset`` code points."""

    check_offset(offset, len(text))
    end = min(offset + READ_PAGE_CODE_POINTS, len(text))
    reply = {"path": path, "size": size, "chars": len(text), "offset": offset,
             "content": text[offset:end]}
    if end < len(text):
        reply["next"] = end
    return reply


def grep_lines(path: str, text: str, pattern: str) -> list[dict]:
    """Every line of ``text`` holding the literal ``pattern``, as matches of ``path``."""

    matches = []
    for index, line in enumerate(text.split("\n")):
        line = line.removesuffix("\r")
        if pattern in line:
            matches.append({"path": path, "line": index + 1, "text": line[:LINE_CODE_POINTS]})
    return matches


def page(header: dict, field: str, items: list[dict], offset: int, most: int) -> dict:
    """One counted page of ``items`` under ``field``, from ``offset``, at most ``most``."""

    check_offset(offset, len(items))
    end = min(offset + most, len(items))
    reply = {**header, field: items[offset:end], "total": len(items), "offset": offset}
    if end < len(items):
        reply["next"] = end
    return reply
