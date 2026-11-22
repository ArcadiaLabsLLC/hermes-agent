"""The verbs' two pattern dialects and a search's deadline, as Eternia's ``file_tree_patterns.dart``.

The rule spec's ``patterns`` section (row
``MC-FU-PROJECT-FOLDER-SEARCH-NARROWS-BY-FILE-NAME-AND-TAKES-A-PATTERN``): a file-name glob
(``tree`` and ``grep`` take one as ``glob``) and a line wildcard (``grep``'s ``pattern`` with
``wildcard``). Neither is a regular expression. These patterns arrive from remote callers over
``runtime.agent.files.*``, and a Python ``re`` match cannot be stopped by a deadline once it runs
(review w1118a.84), so each is matched here without backtracking over the text: the glob with one
remembered ``*`` (at most name x glob steps, both bounded), the wildcard as its literal pieces
found left to right with ``str.find`` (one pass over the line). The deadline is asked between
entries and between lines.
"""

from __future__ import annotations

__layer__ = "models"

import time
from dataclasses import dataclass

from agent_runtime.project_files.rules import (
    MAX_GLOB, MAX_PATTERN, MAX_WILDCARDS, MIN_PATTERN, SEARCH_DEADLINE_MS, ProjectFileRefusal,
)


def check_pattern(pattern: object) -> None:
    """Refuses a ``grep`` pattern outside the spec's length bounds ``bad_argument``."""

    if not isinstance(pattern, str) or not MIN_PATTERN <= len(pattern) <= MAX_PATTERN:
        raise ProjectFileRefusal("bad_argument",
                                 f"pattern must be {MIN_PATTERN}-{MAX_PATTERN} characters")


def _check_wildcards(pattern: str, name: str) -> None:
    if pattern.count("*") > MAX_WILDCARDS:
        raise ProjectFileRefusal("bad_argument", f"{name} holds at most {MAX_WILDCARDS} *")


@dataclass(frozen=True)
class NameGlob:
    """A checked file-name glob: ``*`` any run, ``?`` one character, the rest itself, whole name."""

    pattern: str

    @classmethod
    def parse(cls, pattern: object) -> NameGlob:
        if not isinstance(pattern, str) or not 1 <= len(pattern) <= MAX_GLOB:
            raise ProjectFileRefusal("bad_argument", f"glob must be 1-{MAX_GLOB} characters")
        if "/" in pattern or "\\" in pattern:
            raise ProjectFileRefusal("bad_argument",
                                     "glob matches a file name, so it holds no / or \\")
        _check_wildcards(pattern, "glob")
        return cls(pattern)

    def matches(self, name: str) -> bool:
        glob = self.pattern
        at = following = 0
        star = -1
        mark = 0
        while at < len(name):
            if following < len(glob) and glob[following] == "*":
                star = following
                following += 1
                mark = at
            elif following < len(glob) and glob[following] in ("?", name[at]):
                following += 1
                at += 1
            elif star >= 0:
                following = star + 1
                mark += 1
                at = mark
            else:
                return False
        while following < len(glob) and glob[following] == "*":
            following += 1
        return following == len(glob)


@dataclass(frozen=True)
class LinePattern:
    """A checked ``grep`` pattern: literal, or with ``wildcard`` a ``*`` spanning any run in a line."""

    pattern: str
    pieces: tuple[str, ...]

    @classmethod
    def parse(cls, pattern: object, *, wildcard: object = False) -> LinePattern:
        check_pattern(pattern)
        if not isinstance(wildcard, bool):
            raise ProjectFileRefusal("bad_argument", "wildcard must be true or false")
        if not wildcard:
            return cls(pattern, (pattern,))
        _check_wildcards(pattern, "pattern")
        pieces = tuple(piece for piece in pattern.split("*") if piece)
        if not pieces:
            raise ProjectFileRefusal("bad_argument",
                                     "a wildcard pattern holds a character other than *")
        return cls(pattern, pieces)

    def matches(self, line: str) -> bool:
        start = 0
        for piece in self.pieces:
            found = line.find(piece, start)
            if found < 0:
                return False
            start = found + len(piece)
        return True


class Deadline:
    """The time a search may take; :meth:`check` refuses ``search_timeout`` once it has passed."""

    def __init__(self, seconds: float = SEARCH_DEADLINE_MS / 1000) -> None:
        self.seconds = seconds
        self._ends = time.monotonic() + seconds

    def check(self) -> None:
        if time.monotonic() > self._ends:
            raise ProjectFileRefusal(
                "search_timeout",
                f"the search did not finish within {round(self.seconds * 1000)} ms; "
                "narrow path or glob")
