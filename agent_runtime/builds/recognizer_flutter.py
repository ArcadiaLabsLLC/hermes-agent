"""The Flutter build recognizer: which stage a build is in, read from its own output.

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §4.

* **Stage, from output.** :data:`FLUTTER_STAGES` is a DATA table — one regex per stage,
  in the stage enum's order — read against each new output line. The stage only moves
  FORWARD: a later line matching an earlier stage is ignored (``pub get`` lines after a
  build finished are a plugin's, not a regression). A transcript matching nothing stays
  ``unknown`` — never ``queued``, never ``preparing``.
* **The artifact** comes from the ``✓ Built <path>`` line ONLY (``√`` on a Windows console
  code page), made absolute against the build's cwd. When the build ends without that
  line the artifact is null even if a conventional output directory exists, and the row
  carries ``artifact_unlocated`` naming the directories that would have been probed.
* **Index the unknowns** (owner rule 2026-10-04): a line SHAPED like a phase announcement
  (``^\\w[\\w\\s]{2,40}\\.\\.\\.$``, a trailing elapsed time allowed because real status lines
  carry one, or one that begins ``Running`` / ``Building`` /
  ``Linking`` / ``Compiling`` / ``Launching``) that matches no stage regex is recorded as
  ``stage_line_unrecognized`` with the line as evidence — so a Flutter release that
  renames a phase leaves its new wording ON THE ROW the first time it is seen.

The table is pinned by goldens of REAL transcripts (``tests/fixtures/builds/``); when a
Flutter version changes a phrase the sequence pin reds on the new golden and the fix is
one regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from typing import Any

from agent_runtime.builds.unknowns import (
    UNKNOWN_ARTIFACT_UNLOCATED,
    UNKNOWN_STAGE_LINE_UNRECOGNIZED,
    UnknownsIndex,
    redact_evidence,
)
from agent_runtime.builds.vocabulary import (
    ARTIFACT_KIND_BUNDLE,
    ARTIFACT_KIND_DIRECTORY,
    ARTIFACT_KIND_EXECUTABLE,
    ARTIFACT_KIND_OTHER,
    BUILD_STAGES,
    STAGE_COMPILING,
    STAGE_DONE,
    STAGE_FINISHING,
    STAGE_LINKING,
    STAGE_PACKAGING,
    STAGE_PREPARING,
    STAGE_RESOLVING,
    STAGE_UNKNOWN,
    STAGE_DETAIL_LIMIT,
)

__layer__ = "policy"

#: ``(stage, regex)`` in the stage enum's order. One regex per stage; a line is read
#: against every row and the LATEST matching stage wins, forward only.
FLUTTER_STAGES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (STAGE_PREPARING, re.compile(r"^Launching \S.* on \S.* in \w+ mode\.\.\.")),
    (STAGE_RESOLVING, re.compile(r"^(Resolving dependencies|Downloading packages|Got dependencies|Running \"flutter pub get\")")),
    (STAGE_COMPILING, re.compile(r"^(Building \w[\w ]* application\.\.\.|Compiling lib[\\/])")),
    (STAGE_LINKING, re.compile(r"(\berror LNK\d+:|\bLINK : |^Linking\b)")),
    (STAGE_PACKAGING, re.compile(r"^(Packaging|Bundling|Installing) \S")),
    (STAGE_FINISHING, re.compile(r"^Syncing files to device")),
    (STAGE_DONE, re.compile(r"^[✓√] Built \S")),
)

_BUILT_LINE_RE = re.compile(r"^[✓√] Built (?P<path>.+?)(?:\s+\([\d.]+\s*\w+\))?\s*$")
#: A real status line carries its elapsed time after the ellipsis (``Building … application...   34.6s``).
_PHASE_SHAPED_RE = re.compile(r"^(\w[\w\s]{2,40}\.\.\.(\s+[\d.]+\s*m?s)?|(Running|Building|Linking|Compiling|Launching)\b.*)$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

#: Artifact kind by suffix; a path with no suffix is a directory (a Linux bundle).
_ARTIFACT_KINDS = {
    ".exe": ARTIFACT_KIND_EXECUTABLE,
    ".app": ARTIFACT_KIND_BUNDLE,
    ".apk": ARTIFACT_KIND_BUNDLE,
    ".aab": ARTIFACT_KIND_BUNDLE,
    ".ipa": ARTIFACT_KIND_BUNDLE,
    ".msix": ARTIFACT_KIND_BUNDLE,
}

#: Per target, the conventional output directories the ``artifact_unlocated`` evidence names.
_CONVENTIONAL_OUTPUTS = {
    "windows": lambda mode: [f"build/windows/x64/runner/{mode.capitalize()}", f"build/windows/arm64/runner/{mode.capitalize()}"],
    "linux": lambda mode: [f"build/linux/x64/{mode}/bundle", f"build/linux/arm64/{mode}/bundle"],
    "macos": lambda mode: [f"build/macos/Build/Products/{mode.capitalize()}"],
    "apk": lambda mode: ["build/app/outputs/flutter-apk"],
}

_STAGE_ORDER = {stage: index for index, stage in enumerate(BUILD_STAGES)}


def clean_line(line: str) -> str:
    """One output line with ANSI escapes and carriage-return redraws removed."""

    text = _ANSI_RE.sub("", str(line))
    return text.rsplit("\r", 1)[-1].strip()


def stage_of(line: str) -> str | None:
    """The latest stage whose regex matches ``line``, or None."""

    matched = [stage for stage, pattern in FLUTTER_STAGES if pattern.search(line)]
    return matched[-1] if matched else None


def artifact_kind(path: str) -> str:
    suffix = PureWindowsPath(path).suffix.lower()
    if not suffix:
        return ARTIFACT_KIND_DIRECTORY
    return _ARTIFACT_KINDS.get(suffix, ARTIFACT_KIND_OTHER)


def _absolute(path: str, cwd: str) -> str:
    candidate = PureWindowsPath(path)
    if candidate.is_absolute() or path.startswith("/"):
        return path
    return str(PureWindowsPath(cwd) / candidate) if cwd else path


@dataclass
class FlutterRecognizer:
    """Reads one build's output, line by line; holds the stage, the artifact and the unknowns."""

    cwd: str = ""
    stage: str = STAGE_UNKNOWN
    stage_detail: str = ""
    artifact: dict[str, Any] | None = None
    sequence: list[str] = field(default_factory=list)
    unknowns: UnknownsIndex = field(default_factory=UnknownsIndex)

    def feed(self, text: str, *, seen_at: float) -> None:
        for raw in str(text or "").splitlines():
            self.line(raw, seen_at=seen_at)

    def line(self, raw: str, *, seen_at: float) -> None:
        line = clean_line(raw)
        if not line:
            return
        stage = stage_of(line)
        if stage is None:
            if _PHASE_SHAPED_RE.match(line):
                self.unknowns.add(UNKNOWN_STAGE_LINE_UNRECOGNIZED, line, seen_at)
            return
        self._advance(stage, line)
        built = _BUILT_LINE_RE.match(line)
        if built is not None:
            path = _absolute(built.group("path").strip(), self.cwd)
            self.artifact = {"path": path, "kind": artifact_kind(path)}

    def _advance(self, stage: str, line: str) -> None:
        if self.stage != STAGE_UNKNOWN and _STAGE_ORDER[stage] <= _STAGE_ORDER[self.stage]:
            return
        self.stage = stage
        self.stage_detail = redact_evidence(line)[:STAGE_DETAIL_LIMIT]
        self.sequence.append(stage)

    def finish(self, *, target: str, mode: str, seen_at: float) -> None:
        """The build ended: with no ``Built`` line, index ``artifact_unlocated`` with what would be probed."""

        if self.artifact is not None:
            return
        layout = _CONVENTIONAL_OUTPUTS.get(target)
        probed = layout(mode or "release") if layout is not None else []
        evidence = "no 'Built' line; conventional outputs: " + ("; ".join(probed) if probed else f"none known for target {target!r}")
        self.unknowns.add(UNKNOWN_ARTIFACT_UNLOCATED, evidence, seen_at)


def recognize_transcript(text: str, *, cwd: str = "", seen_at: float = 0.0) -> FlutterRecognizer:
    """A whole transcript, read in one pass (the goldens' entry point)."""

    recognizer = FlutterRecognizer(cwd=cwd)
    recognizer.feed(text, seen_at=seen_at)
    return recognizer
