"""What a walk (``tree``, ``grep``) skips: ``.git``, the skip list, the root ``.gitignore``.

The ``.gitignore`` subset is the spec's ``ignore.gitignore`` rule, written the same way as
Eternia's ``FileTreeIgnore``: negation and nested ignore files are documented edge cases,
not worked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_runtime.project_files.rules import NEVER_LISTED, SKIP_DIRECTORIES


@dataclass(frozen=True)
class _Pattern:
    regex: re.Pattern[str]
    anchored: bool
    dir_only: bool

    def matches(self, path: str, name: str, *, is_directory: bool) -> bool:
        if self.dir_only and not is_directory:
            return False
        return self.regex.fullmatch(path if self.anchored else name) is not None


def _glob_to_regex(glob: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("/**", i) and i + 3 == len(glob):
            out.append("/.*")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return "".join(out)


@dataclass(frozen=True)
class SkipRules:
    """The skip rules of one root."""

    patterns: tuple[_Pattern, ...] = ()

    @classmethod
    def parse(cls, gitignore: str) -> SkipRules:
        patterns: list[_Pattern] = []
        for line in gitignore.split("\n"):
            line = line.removesuffix("\r")
            line = line.rstrip(" \t")
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            dir_only = line.endswith("/")
            if dir_only:
                line = line[:-1]
            anchored = "/" in line
            line = line.removeprefix("/")
            if not line:
                continue
            patterns.append(_Pattern(re.compile(_glob_to_regex(line)), anchored, dir_only))
        return cls(tuple(patterns))

    def skips(self, path: str, *, is_directory: bool) -> bool:
        """Whether a walk skips the entry at root-relative ``path``."""

        name = path.rsplit("/", 1)[-1]
        if name in NEVER_LISTED:
            return True
        if is_directory and name in SKIP_DIRECTORIES:
            return True
        return any(p.matches(path, name, is_directory=is_directory) for p in self.patterns)
