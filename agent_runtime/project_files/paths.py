"""The root-relative path grammar of a project folder (the spec's ``path_grammar``)."""

from __future__ import annotations

__layer__ = "models"

import re

from agent_runtime.project_files.rules import MAX_PATH_LENGTH, NEVER_LISTED, ProjectFileRefusal

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")


def _broken_rule(raw: str) -> str | None:
    if raw == "":
        return "the path is empty"
    if len(raw) > MAX_PATH_LENGTH:
        return f"the path is over {MAX_PATH_LENGTH} characters"
    if _CONTROL.search(raw):
        return "the path holds a control character"
    if raw.startswith("/"):
        return "the path is absolute; give it relative to the root"
    if "\\" in raw:
        return "the path uses \\ instead of /"
    if _DRIVE_LETTER.match(raw):
        return "the path starts with a drive letter"
    for segment in raw.split("/"):
        if segment == "":
            return "the path has an empty segment"
        if segment in (".", ".."):
            return "the path has a . or .. segment"
    return None


def parse_path(raw: str | None) -> tuple[str, ...]:
    """The segments of ``raw`` (none for the root, ``raw is None``); refused ``invalid_path``."""

    if raw is None:
        return ()
    broke = _broken_rule(raw)
    if broke is not None:
        raise ProjectFileRefusal("invalid_path", f"{broke}: {raw!r}")
    return tuple(raw.split("/"))


def is_never_listed(segments: tuple[str, ...]) -> bool:
    """Whether the path is, or is inside, a never-listed folder (``.git``)."""

    return any(segment in NEVER_LISTED for segment in segments)
