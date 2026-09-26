from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any

from hermes_time import now

from . import paths
from .machine_roots import load_machine_roots

__layer__ = "stores"

# Keep the base short enough that large repos with deep generated paths do not
# fail halfway through worktree materialization on Windows path limits.
HARNESS_WORKTREE_BASE_MAX_CHARS = 55


def _worktree_base_dir() -> Path:
    candidate = paths.store_root() / "wt"
    if len(str(candidate)) <= HARNESS_WORKTREE_BASE_MAX_CHARS:
        return candidate
    return Path(tempfile.gettempdir()) / "hermes-agent-wt"


def _remove_harness_worktree(source_root: Path, worktree: Path, *, reason: str) -> bool:
    severed = _sever_worktree_reparse_points(worktree)
    if severed:
        _log_worktree_event(
            "worktree_links_severed",
            {"worktree": str(worktree), "count": severed, "reason": reason},
        )
    result = subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=source_root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    if result.returncode == 0:
        _log_worktree_event(
            "worktree_gc_removed",
            {"worktree": str(worktree), "source_root_label": source_root.name, "reason": reason},
        )
        return True
    return False


def _sever_worktree_reparse_points(worktree: Path) -> int:
    """Delete link entries (junctions / symlinks) inside a worktree WITHOUT
    recursing into their targets, returning how many links were severed.

    ``git worktree remove --force`` on Git for Windows traverses directory
    junctions as plain directories, so removing a worktree that carries a
    support junction (e.g. the ``.EterniaBackendVirtualEnv`` link materialized
    for backend self-tests) deletes the REAL target's contents along with the
    worktree. This happened live on 2026-07-01: the first count-cap GC burst
    emptied the backend repo's virtualenv through exactly this traversal,
    and every backend goal afterwards lost its interpreter. Severing the link
    entries first guarantees only the link dies with the worktree.
    """

    severed = 0
    stack = [worktree]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                if _entry_is_reparse_point(entry):
                    if _remove_link_entry(entry.path):
                        severed += 1
                    else:
                        _log_worktree_event(
                            "worktree_link_sever_failed",
                            {"worktree": str(worktree), "link": entry.name},
                        )
                    continue
                if entry.is_dir(follow_symlinks=False) and entry.name != ".git":
                    stack.append(Path(entry.path))
            except OSError:
                continue
    return severed


def _entry_is_reparse_point(entry: os.DirEntry) -> bool:
    if entry.is_symlink():
        return True
    if os.name != "nt":
        return False
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _remove_link_entry(path: str) -> bool:
    """Remove a link entry itself (never its target's contents)."""
    try:
        os.rmdir(path)  # junction / directory symlink: drops the reparse point only
        return True
    except OSError:
        pass
    try:
        os.unlink(path)  # file symlink
        return True
    except OSError:
        return False


def _run_git_quiet(cwd: Path, args: list[str]) -> None:
    subprocess.run(
        args,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )


def worktree_patch_text(worktree: Path, *, include_untracked: bool = True, timeout_seconds: int = 60) -> str:
    """Binary-safe unified patch of a worktree's changes vs HEAD.

    Raw ``git diff --binary`` stdout — deliberately NOT routed through
    ``_git_output``, which strips/drops lines and would corrupt patch context.
    ``--intent-to-add`` makes untracked files appear as new-file hunks without
    staging content.
    """

    root = _git_root_for(Path(worktree).expanduser())
    if root is None:
        return ""
    if include_untracked:
        _run_git_quiet(root, ["git", "add", "--all", "--intent-to-add"])
    try:
        # Byte-faithful capture: text mode would apply universal-newline
        # translation and silently strip CR from CRLF content, producing a
        # patch that no longer applies to CRLF working trees.
        result = subprocess.run(
            ["git", "diff", "--binary", "--no-ext-diff", "HEAD"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode not in {0, 1}:
        return ""
    text = (result.stdout or b"").decode("utf-8", errors="replace")
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def worktree_patch_size_estimate(worktree: Path, *, timeout_seconds: int = 60) -> int:
    """Estimate capture bytes without changing the worktree or its index.

    Tracked changes use the exact binary-diff byte count. Untracked content is
    represented by its file bytes plus a small per-path patch-header allowance;
    this is deliberately an estimate because producing the exact add-file patch
    would require ``git add --intent-to-add``, which is forbidden on preview.
    """

    root = _git_root_for(Path(worktree).expanduser())
    if root is None:
        return 0
    try:
        tracked = subprocess.run(
            ["git", "diff", "--binary", "--no-ext-diff", "HEAD"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except Exception:
        return 0
    if tracked.returncode not in {0, 1} or untracked.returncode != 0:
        return 0
    estimate = len(tracked.stdout or b"")
    for raw_path in (untracked.stdout or b"").split(b"\0"):
        if not raw_path:
            continue
        relative = raw_path.decode("utf-8", errors="surrogateescape")
        candidate = root / relative
        try:
            content_bytes = candidate.stat().st_size if candidate.is_file() else 0
        except OSError:
            content_bytes = 0
        estimate += content_bytes + len(raw_path) + 128
    return estimate


def legacy_harness_worktree_base_dir() -> Path:
    """Canonical pre-short-root fallback used by older Harness releases."""

    return Path(tempfile.gettempdir()) / "hermes-agent-wt"


def current_harness_worktree_base_dir() -> Path:
    return _worktree_base_dir()


def harness_worktree_inventory(
    *, include_legacy_temp: bool = False
) -> list[tuple[Path, Path, str, str | None]]:
    """Managed worktree directories with typed base provenance, deduplicated."""

    bases = [(_worktree_base_dir(), "current")]
    if include_legacy_temp:
        bases.append((legacy_harness_worktree_base_dir(), "legacy_temp"))
    rows: list[tuple[Path, Path, str, str | None]] = []
    seen: set[Path] = set()
    for base, source in bases:
        if _path_is_reparse_point(base):
            rows.append((base, base, source, "base_reparse_alias"))
            continue
        if not base.is_dir():
            continue
        try:
            resolved_base = base.resolve()
        except OSError:
            rows.append((base, base, source, "base_unresolvable"))
            continue
        for worktree in base.iterdir():
            if _path_is_reparse_point(worktree):
                rows.append((worktree, base, source, "candidate_reparse_alias"))
                continue
            if not worktree.is_dir():
                continue
            try:
                resolved = worktree.resolve()
            except OSError:
                rows.append((worktree, base, source, "candidate_unresolvable"))
                continue
            if resolved.parent != resolved_base:
                rows.append((worktree, base, source, "candidate_outside_base"))
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            rows.append((worktree, base, source, None))
    return sorted(rows, key=lambda row: paths.safe_mtime(row[0]))


def _path_is_reparse_point(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        if os.name != "nt":
            return False
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def worktree_source_root(worktree: Path) -> Path | None:
    """Main repository root a harness worktree belongs to (via git-common-dir)."""

    git_dir_text = _git_output(Path(worktree), ["git", "rev-parse", "--git-common-dir"], single=True)
    if not git_dir_text:
        return None
    git_dir = Path(git_dir_text)
    if not git_dir.is_absolute():
        git_dir = Path(worktree) / git_dir
    # <repo>/.git → repo root
    root = git_dir.resolve().parent
    return root if root.is_dir() else None


def remove_orphan_worktree(worktree: Path, *, reason: str) -> bool:
    """Reap a worktree by resolving its own source repo, then prune."""

    source_root = worktree_source_root(worktree)
    if source_root is None:
        return False
    removed = _remove_harness_worktree(source_root, Path(worktree), reason=reason)
    if removed:
        _run_git_quiet(source_root, ["git", "worktree", "prune"])
    return removed


def safe_affected_repo_labels(repos: list[str] | tuple[str, ...] | None) -> list[str]:
    labels: list[str] = []
    for repo in repos or []:
        text = str(repo or "").strip()
        if not text:
            continue
        alias = _normalize_repo_alias(text)
        if alias:
            display_label = _repo_alias_display_label(alias)
            if display_label is not None:
                labels.append(display_label)
                continue
        resolved = resolve_affected_repo_workdir(text)
        if resolved is not None:
            labels.append(_safe_repo_label(resolved.name))
            continue
        if alias:
            labels.append(f"{_safe_repo_label(alias)} (unresolved)")
            continue
        name = Path(text).name if (":" in text or "/" in text or "\\" in text) else text
        labels.append(f"{_safe_repo_label(name)} (unresolved; path withheld)")
    return labels


def _git_output(workdir: Path, command: list[str], *, single: bool = False) -> Any:
    try:
        result = subprocess.run(
            command,
            cwd=workdir,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except Exception:
        return "" if single else []
    if result.returncode not in {0, 1}:
        return "" if single else []
    text = (result.stdout or "").rstrip()
    if single:
        return text.strip().splitlines()[0].strip() if text.strip() else ""
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def resolve_affected_repo_workdir(repo: str) -> Path | None:
    path = Path(repo).expanduser()
    if path.is_absolute() and path.is_dir():
        return _git_root_for(path) or path

    alias = _normalize_repo_alias(repo)
    root_name = _REPO_ALIAS_MACHINE_ROOTS.get(alias)
    if root_name is not None:
        resolved = load_machine_roots().get(root_name)
        if resolved is not None and resolved.is_dir():
            return _git_root_for(resolved) or resolved
    if alias in _HARNESS_REPO_ALIASES:
        root = Path(__file__).resolve().parents[1]
        if root.is_dir():
            return root
    return None


def _git_root_for(path: Path) -> Path | None:
    current = path.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _log_worktree_event(event_type: str, payload: dict[str, Any]) -> None:
    try:
        path = paths.store_root() / "worktree_events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": 1,
            "ts": now().isoformat(),
            "type": event_type,
            **payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except Exception:
        return


def _safe_repo_label(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-._")
    return cleaned[:64] or "repo"


def _normalize_repo_alias(value: str) -> str:
    stripped = value.strip().lower()
    if re.search(r"[^a-z0-9 _-]", stripped):
        return ""
    return re.sub(r"[ _-]+", "-", stripped).strip("-")


_HARNESS_REPO_ALIASES = frozenset({"agent-runtime-harness", "hermes-agent"})
_REPO_ALIAS_MACHINE_ROOTS = {
    "eterniabackend": "eternia_backend",
    "eternia-backend": "eternia_backend",
    "backend": "eternia_backend",
    "eternialauncher": "eternia_launcher",
    "eternia-launcher": "eternia_launcher",
    "frontend": "eternia_launcher",
    "launcher": "eternia_launcher",
}

_REPO_ALIAS_DISPLAY_LABELS = {
    "eterniabackend": "EterniaBackend",
    "eternia-backend": "EterniaBackend",
    "backend": "EterniaBackend",
    "eternialauncher": "EterniaLauncher",
    "eternia-launcher": "EterniaLauncher",
    "frontend": "EterniaLauncher",
    "launcher": "EterniaLauncher",
    "agent-runtime-harness": "hermes-agent",
    "hermes-agent": "hermes-agent",
}


def _repo_alias_display_label(alias: str) -> str | None:
    return _REPO_ALIAS_DISPLAY_LABELS.get(alias)
