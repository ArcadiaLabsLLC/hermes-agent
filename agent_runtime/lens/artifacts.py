"""What an Episode's turn left behind: its folder, the receipt's two lists, and the one read door.

Plan ``p10-agent-2026-10-19.md`` §5.2 decision 4. Every Episode owns a folder,
``<head home>/lens/episodes/<episode_id>/`` (resolved at call time). After the
turn, :func:`collect` gives the receipt

* ``artifact_handles`` — ``media_handles.mint_reply_media(reply)``: the IMAGES the
  reply declared with ``MEDIA:`` lines (that module's exfiltration rule, unwidened);
* ``files`` — every regular file under the folder (``name, size_bytes, sha256``),
  so a ``report.md`` is on the receipt without a handle.

The forged turn is read-only (owner RULED 2026-10-22) and writes nothing, so the door writes
its reply as that ``report.md`` (:func:`write_reply_report`, plan
``planned/lens-deadline-schedule-equivalence-report-2026-10-27.md`` §4) before ``collect``.

:func:`read_artifact` (``runtime.lens.artifact``) serves one of those files and
only from inside that folder: an absolute name, a ``..`` walk and a symlink that
resolves outside are refused alike, as is a file over :data:`MAXIMUM_ARTIFACT_BYTES`
or of a type outside :data:`ARTIFACT_TYPES`.
"""

from __future__ import annotations

import base64
import hashlib
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from .wire_value import bounded_string, digest_value

__layer__ = "stores"

MAXIMUM_ARTIFACT_BYTES = 1024 * 1024
MAXIMUM_FILES = 64
#: suffix -> (media type, encoding on the wire). Text is served as UTF-8, images as base64.
ARTIFACT_TYPES = {
    ".md": ("text/markdown", "utf-8"), ".txt": ("text/plain", "utf-8"), ".json": ("application/json", "utf-8"),
    ".csv": ("text/csv", "utf-8"), ".log": ("text/plain", "utf-8"),
    ".png": ("image/png", "base64"), ".jpg": ("image/jpeg", "base64"), ".jpeg": ("image/jpeg", "base64"),
    ".gif": ("image/gif", "base64"), ".webp": ("image/webp", "base64"),
}


#: The file the door writes the turn's reply into (:func:`write_reply_report`).
REPLY_REPORT_NAME = "report.md"
#: The last line of a reply cut to fit :data:`MAXIMUM_ARTIFACT_BYTES`; ``{}`` is the bytes cut.
REPLY_TRUNCATED_LINE = "\n[truncated: {} bytes]\n"


class ArtifactRefusal(str, Enum):
    NOT_FOUND = "artifact_not_found"
    OUTSIDE_FOLDER = "outside_episode_folder"
    TOO_LARGE = "artifact_too_large"
    UNSUPPORTED_TYPE = "unsupported_type"


class LensArtifactError(ValueError):
    def __init__(self, code: ArtifactRefusal) -> None:
        super().__init__(code.value)
        self.code = code


def episodes_root() -> Path:
    from .store import lens_root

    return lens_root() / "episodes"


def episode_folder(episode_id: str) -> Path:
    """The Episode's folder (not created); the id must be an Episode digest."""

    return episodes_root() / digest_value(episode_id)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def folder_files(episode_id: str) -> list[dict[str, Any]]:
    """Regular files under the folder (symlinks skipped), sorted by name, at most :data:`MAXIMUM_FILES`."""

    folder = episode_folder(episode_id)
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.rglob("*")):
        if len(found) >= MAXIMUM_FILES:
            break
        if path.is_symlink() or not path.is_file():
            continue
        try:
            found.append({"name": path.relative_to(folder).as_posix(), "size_bytes": path.stat().st_size,
                          "sha256": _file_digest(path)})
        except OSError:
            continue
    return found


def _fitted(data: bytes) -> bytes:
    """``data`` cut on a character boundary, with its truncation line, to at most :data:`MAXIMUM_ARTIFACT_BYTES`."""

    if len(data) <= MAXIMUM_ARTIFACT_BYTES:
        return data
    keep = MAXIMUM_ARTIFACT_BYTES - len(REPLY_TRUNCATED_LINE.format(len(data)).encode("utf-8"))
    head = data[:keep].decode("utf-8", errors="ignore").encode("utf-8")
    return head + REPLY_TRUNCATED_LINE.format(len(data) - len(head)).encode("utf-8")


def write_reply_report(episode_id: str, reply_text: Any) -> bool:
    """Write the turn's reply as the Episode's ``report.md`` (UTF-8, exclusive create — an existing
    one is kept, so a re-entered turn never overwrites it). Nothing for an empty or absent reply.
    True when written. Never raises: a turn's receipt is not lost to a disk error."""

    if not isinstance(reply_text, str) or not reply_text.strip():
        return False
    folder = episode_folder(episode_id)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / REPLY_REPORT_NAME).open("xb") as handle:
            handle.write(_fitted(reply_text.encode("utf-8")))
    except OSError:  # FileExistsError included: the first report stands
        return False
    return True


def collect(episode_id: str, reply_text: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(artifact_handles, files)`` for the receipt. Never raises: a turn's output is not lost to a hash."""

    from agent_runtime.media_handles import mint_reply_media

    try:
        handles = mint_reply_media(reply_text or "")
    except Exception:
        handles = []
    try:
        files = folder_files(episode_id)
    except OSError:
        files = []
    return handles, files


def resolve_inside(folder: Path, name: str) -> Path:
    """``folder / name``, resolved, or :class:`LensArtifactError` when it lands outside ``folder``."""

    relative = PurePosixPath(bounded_string(name, maximum=512).replace("\\", "/"))
    if relative.is_absolute() or ":" in relative.as_posix():
        raise LensArtifactError(ArtifactRefusal.OUTSIDE_FOLDER)
    root = folder.resolve()
    resolved = (root / Path(*relative.parts)).resolve()
    if not resolved.is_relative_to(root):
        raise LensArtifactError(ArtifactRefusal.OUTSIDE_FOLDER)
    return resolved


def read_artifact(episode_id: str, name: str) -> dict[str, Any]:
    folder = episode_folder(episode_id)
    path = resolve_inside(folder, name)
    if not path.is_file():
        raise LensArtifactError(ArtifactRefusal.NOT_FOUND)
    kind = ARTIFACT_TYPES.get(path.suffix.lower())
    if kind is None:
        raise LensArtifactError(ArtifactRefusal.UNSUPPORTED_TYPE)
    if path.stat().st_size > MAXIMUM_ARTIFACT_BYTES:
        raise LensArtifactError(ArtifactRefusal.TOO_LARGE)
    data = path.read_bytes()
    media_type, encoding = kind
    content = data.decode("utf-8", errors="replace") if encoding == "utf-8" else base64.b64encode(data).decode("ascii")
    return {"episode_id": episode_id, "name": path.relative_to(folder.resolve()).as_posix(), "media_type": media_type,
            "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "encoding": encoding,
            "content": content}
