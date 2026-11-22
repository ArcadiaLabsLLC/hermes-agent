"""The second engine for a phone's regex search: the ``regex`` package, bounded by its ``timeout=``.

Row ``RT-PHONE-REGEX-SEARCH-RUNS-RIPGREPS-MATCHER-FROM-A-NATIVE-LIBRARY`` (plan
``docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md`` §8, owner RULED
2026-11-21): ripgrep's engine first (``native_match``); where it is not there, the ``regex`` package,
whose matches backtrack, so every line's match is handed what is left of the search's
:class:`patterns.Deadline` as its ``timeout=``; where neither is there, regex is refused in words. Python
``re`` never runs on a caller's pattern: it cannot be stopped once it runs.

The ``regex`` import is guarded and lazy: a phone without the package (none pins it yet) answers
"not available", and the profile closure counts the package only where an extra already ships it.
"""

from __future__ import annotations

__layer__ = "stores"

from agent_runtime.project_files.patterns import Deadline
from agent_runtime.project_files.rules import ProjectFileRefusal

__all__ = ["RegexPackageLines", "available"]


def _package():
    try:
        import regex
    except ImportError:
        return None
    return regex


def available() -> bool:
    """Whether the ``regex`` package imports here."""

    return _package() is not None


class RegexPackageLines:
    """A pattern compiled by the ``regex`` package, matched one line at a time under the deadline."""

    def __init__(self, compiled, cancel=None) -> None:
        self._compiled = compiled
        self.cancel = cancel

    @classmethod
    def compile(cls, pattern: str, *, ignore_case: bool = False, cancel=None) -> RegexPackageLines | None:
        """``pattern`` compiled, None when the package is not there; refused ``bad_argument`` in its words."""

        package = _package()
        if package is None:
            return None
        try:
            compiled = package.compile(pattern, package.IGNORECASE if ignore_case else 0)
        except package.error as error:
            raise ProjectFileRefusal("bad_argument", f"the regex is refused: {error}") from None
        return cls(compiled, cancel)

    def close(self) -> None:
        """Nothing to free; here so the search closes either engine's matcher the same way."""

    def matching_lines(self, text: str, lines: list[str], deadline: Deadline | None = None) -> list[int]:
        """``replies.LineMatcher``: each line searched with the deadline's remaining time as ``timeout=``."""

        deadline = deadline or Deadline()
        if self.cancel is not None:
            self.cancel.check()
        found = []
        for index, line in enumerate(lines):
            deadline.check()
            try:
                # MUTATION: drop timeout= and a catastrophic pattern runs past the deadline
                # (test_project_files_native_match: test_the_regex_package_fallback_is_bounded_by_the_deadline).
                hit = self._compiled.search(line, timeout=max(0.001, deadline.remaining_ms() / 1000))
            except TimeoutError:
                raise deadline.refusal() from None
            if hit is not None:
                found.append(index)
        return found
