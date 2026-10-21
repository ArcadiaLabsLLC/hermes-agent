"""Which lines of the tree are the fork's: the line fact the fork-scoped lint gate judges by.

A file is UPSTREAM iff its path is in ``tests/fixtures/upstream_manifest.txt`` (the
footprint's rule, ``scripts/upstream_footprint.py``). Every line of a file that is not
upstream is a fork line. In an upstream file a line is a fork line iff it is ADDED against
the upstream base blob: the ``+`` side of ``git diff --unified=0 <base>`` over that file.
A line present at the base, or only re-numbered around a fork hunk, is upstream's.

The base is, in order: an explicit ``base_ref``; ``git merge-base upstream/main HEAD``
when the ``upstream/main`` ref exists (a merge lane's checkout); the manifest's
``# base <sha>`` header (CI and any clone without the upstream remote).

The diff is taken against the WORKING TREE of ``root`` under ``env``, so a
``scripts/check`` snapshot (``GIT_WORK_TREE`` = the snapshot) is judged by its own bytes.
Plan: ``docs/agent-runtime-harness/planned/fork-seam-line-lint-2026-10-21.md`` F1.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

MANIFEST_REL = Path("tests") / "fixtures" / "upstream_manifest.txt"
UPSTREAM_REF = "upstream/main"

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_PATHSPEC_CHUNK = 200


class ForkLinesUnavailable(RuntimeError):
    """The base or the manifest cannot be read; the caller judges every line."""


def added_lines(unified0: str) -> dict[str, set[int]]:
    """``git diff --unified=0 --no-renames`` text -> ``{path: new-side line numbers added}``.

    Only the ``+`` side of each hunk header counts: ``+c,d`` adds lines ``c .. c+d-1``
    (``d`` absent means 1, ``d == 0`` a pure deletion). The ``-`` side numbers lines of
    the BASE blob and never name a line of the tree.
    """
    out: dict[str, set[int]] = {}
    path: str | None = None
    for line in unified0.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            path = None if target == "/dev/null" else target.removeprefix("b/")
            if path is not None:
                out.setdefault(path, set())
            continue
        match = _HUNK.match(line)
        if match and path is not None:
            start, count = int(match.group(1)), int(match.group(2) or "1")
            out[path].update(range(start, start + count))
    return out


def _git(root: Path, env: dict[str, str] | None, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.quotepath=off", *args], cwd=root, env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=300,
        check=False,
    )


def _manifest_base_and_paths(root: Path) -> tuple[str | None, frozenset[str]]:
    path = root / MANIFEST_REL
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ForkLinesUnavailable(f"no upstream manifest at {MANIFEST_REL.as_posix()}: {exc}") from exc
    base: str | None = None
    paths: set[str] = set()
    for line in text.splitlines():
        if line.startswith("#"):
            match = re.match(r"#\s*base\s+([0-9a-fA-F]+)", line)
            if match and base is None:
                base = match.group(1)
        elif line:
            paths.add(line)
    return base, frozenset(paths)


def _resolve_base(root: Path, env: dict[str, str] | None, explicit: str | None,
                  manifest_base: str | None) -> str:
    if explicit:
        return explicit
    if _git(root, env, "rev-parse", "--verify", "-q", UPSTREAM_REF).returncode == 0:
        merge_base = _git(root, env, "merge-base", UPSTREAM_REF, "HEAD")
        if merge_base.returncode == 0 and merge_base.stdout.strip():
            return merge_base.stdout.strip()
    if manifest_base:
        return manifest_base
    raise ForkLinesUnavailable(f"no {UPSTREAM_REF} ref and no '# base <sha>' header in the manifest")


@dataclass(frozen=True)
class ForkLines:
    """``lines[path]``: the fork's line numbers in each touched upstream file; a path outside
    ``upstream`` is fork-owned whole."""

    root: Path
    base: str
    upstream: frozenset[str]
    lines: dict[str, frozenset[int]]

    @classmethod
    def load(cls, root: Path, base_ref: str | None = None,
             env: dict[str, str] | None = None) -> ForkLines:
        root = Path(root)
        manifest_base, upstream = _manifest_base_and_paths(root)
        base = _resolve_base(root, env, base_ref, manifest_base)
        numstat = _git(root, env, "diff", "--numstat", "-z", "--no-renames", base)
        if numstat.returncode != 0:
            raise ForkLinesUnavailable(f"git diff --numstat {base} failed: {numstat.stderr.strip()}")
        touched = sorted(
            path for record in numstat.stdout.split("\0") if record.count("\t") >= 2
            for path in [record.split("\t", 2)[2]] if path in upstream
        )
        lines: dict[str, frozenset[int]] = {}
        for i in range(0, len(touched), _PATHSPEC_CHUNK):
            diff = _git(root, env, "diff", "--unified=0", "--no-renames", "--no-color", base, "--",
                        *touched[i:i + _PATHSPEC_CHUNK])
            if diff.returncode != 0:
                raise ForkLinesUnavailable(f"git diff -U0 {base} failed: {diff.stderr.strip()}")
            for path, numbers in added_lines(diff.stdout).items():
                lines[path] = frozenset(numbers)
        return cls(root=root, base=base, upstream=upstream, lines=lines)

    def relative(self, path: str | Path) -> str:
        candidate = Path(path)
        if candidate.is_absolute():
            for root in (self.root, self.root.resolve()):
                for target in (candidate, candidate.resolve()):
                    try:
                        return target.relative_to(root).as_posix()
                    except ValueError:
                        continue
        return candidate.as_posix().removeprefix("./")

    def owner(self, path: str | Path) -> str:
        """``fork`` (not an upstream file), ``seam`` (upstream file with fork lines) or ``upstream``."""
        rel = self.relative(path)
        if rel not in self.upstream:
            return "fork"
        return "seam" if self.lines.get(rel) else "upstream"

    def is_fork_line(self, path: str | Path, line: int) -> bool:
        rel = self.relative(path)
        if rel not in self.upstream:
            return True
        return line in self.lines.get(rel, frozenset())

    def summary(self) -> str:
        seams = sum(1 for numbers in self.lines.values() if numbers)
        added = sum(len(numbers) for numbers in self.lines.values())
        return (f"[fork-lines] base={self.base[:10]} upstream_files={len(self.upstream)}"
                f" seam_files={seams} fork_lines_in_seams={added}")
