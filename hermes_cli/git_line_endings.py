"""The user's line-ending config, carried into Hermes's config-isolated internal git.

``noninteractive_git_env`` blanks global and system git config so a user's config cannot hang or
mutate plumbing calls. That also drops ``core.autocrlf`` / ``core.eol``, which only decide how
text is converted between the index and the work tree. Git for Windows writes
``core.autocrlf=true`` into its SYSTEM config by default, so a CRLF checkout made by the user's own
git reads as "every text file modified" to an isolated ``git status`` (worktree GC kept clean
trees as "uncommitted tracked changes"). Replaying these two keys restores the user's own view of
the work tree; neither runs a command, so the replay widens nothing the isolation guards.

Read once per config-file state (system, then global: git's precedence), with values outside the
documented set dropped. Fork-owned; the upstream seam is one line in
``hermes_cli/_subprocess_compat.noninteractive_git_env`` marked ``# fork seam: r-plugins``.
"""

from __future__ import annotations

import os
import subprocess
from typing import Mapping

from hermes_cli._subprocess_compat import windows_hide_flags

# The only keys replayed, each with the values git documents for it.
_ALLOWED: dict[str, frozenset[str]] = {
    "core.autocrlf": frozenset({"true", "false", "input"}),
    "core.eol": frozenset({"lf", "crlf", "native"}),
}
_KEYS_REGEXP = r"^core\.(autocrlf|eol)$"

_cache: dict[tuple, list[tuple[str, str]]] = {}


def _cache_key(env: Mapping[str, str]) -> tuple:
    """Everything that picks the system/global files, plus the global candidates' mtimes."""
    home = env.get("HOME") or env.get("USERPROFILE") or ""
    xdg = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    stamps = []
    for path in (
        env.get("GIT_CONFIG_SYSTEM") or "/etc/gitconfig",
        env.get("GIT_CONFIG_GLOBAL") or os.path.join(home, ".gitconfig"),
        os.path.join(xdg, "git", "config"),
    ):
        try:
            stamps.append(os.stat(path).st_mtime_ns)
        except OSError:
            stamps.append(None)
    return (
        env.get("GIT_CONFIG_GLOBAL"), env.get("GIT_CONFIG_SYSTEM"), env.get("GIT_CONFIG_NOSYSTEM"),
        home, env.get("XDG_CONFIG_HOME"), env.get("PATH"), *stamps,
    )


def _read(env: Mapping[str, str]) -> list[tuple[str, str]]:
    probe_env = {k: v for k, v in env.items()
                 if k != "GIT_CONFIG_PARAMETERS" and not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    probe_env.pop("GIT_CONFIG_COUNT", None)
    probe_env["GIT_TERMINAL_PROMPT"] = "0"
    effective: dict[str, str] = {}
    for scope in ("--system", "--global"):  # lowest precedence first; a later scope overrides
        try:
            proc = subprocess.run(
                ["git", "config", scope, "-z", "--get-regexp", _KEYS_REGEXP],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=5, stdin=subprocess.DEVNULL, env=probe_env, check=False,
                creationflags=windows_hide_flags(),
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode != 0:
            continue
        for record in proc.stdout.split("\0"):
            key, _, value = record.partition("\n")
            key, value = key.strip().lower(), value.strip().lower()
            if value in _ALLOWED.get(key, ()):
                effective[key] = value
    return sorted(effective.items())


def user_line_ending_overrides(base_env: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    """``(key, value)`` pairs for the user's effective system/global ``core.autocrlf``/``core.eol``."""
    env = base_env if base_env is not None else os.environ
    key = _cache_key(env)
    cached = _cache.get(key)
    if cached is None:
        cached = _cache[key] = _read(env)
    return list(cached)
