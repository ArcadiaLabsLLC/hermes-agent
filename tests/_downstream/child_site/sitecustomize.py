"""Start-up shortcut for the hermes children a test session spawns (fork-owned, test-only).

This directory is put on ``PYTHONPATH`` by the session chain (``tests/_downstream/child_startup.py``),
so every Python process a test spawns imports this module at start-up. It does nothing unless
``HERMES_TEST_CHILD_STARTUP`` names the snapshot directory, and nothing in a process that is
itself a pytest run (an inner pytest keeps every production path live for its own tests).

In a test child it installs post-import hooks on three modules:

* ``hermes_cli.version_info``: ``_git_version_info`` of THIS checkout is answered from the
  snapshot when HEAD's commit (read from the git files, no process) matches the recorded one;
  a miss runs git once and records the answer for every later child. ``dirty`` is the recording
  child's answer for that commit.
* ``utils``: ``fast_safe_load`` of a file under this checkout's ``plugins/`` tree (the bundled
  provider/platform manifests every child parses while importing ``hermes_cli.config``) is
  answered from the snapshot while the file's ``(mtime_ns, size)`` is unchanged.
* ``hermes_cli.banner``: the background update check and banner prefetch stay off, as they are
  under pytest (``_skip_background_prefetch``); in a child they spawned eight git processes.

Every hook and every snapshot read or write swallows its own failure: a broken shortcut leaves
the child on the production path, never broken. Stdlib only.
"""

from __future__ import annotations

import copy
import importlib.abc
import json
import os
import sys

ENV = "HERMES_TEST_CHILD_STARTUP"
VERSION_FILE = "version.json"
MANIFEST_FILE = "manifests.json"
_REPO = os.path.normcase(os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))
_PLUGINS = os.path.join(_REPO, os.path.normcase("plugins")) + os.sep

# What this process did, for the contract test: names of the shortcut paths taken.
stats = {"version_hit": 0, "version_miss": 0, "manifest_hit": 0, "manifest_miss": 0, "prefetch_off": 0}


def _active() -> bool:
    return bool(os.environ.get(ENV)) and "pytest" not in sys.modules


def _read(name: str) -> dict:
    try:
        with open(os.path.join(os.environ[ENV], name), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, KeyError):
        return {}


def _write(name: str, data: dict) -> None:
    try:
        directory = os.environ[ENV]
        os.makedirs(directory, exist_ok=True)
        tmp = os.path.join(directory, f".{name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, os.path.join(directory, name))
    except (OSError, KeyError, TypeError, ValueError):
        pass


# ── hermes_cli.version_info ──────────────────────────────────────────────────

def _hook_version_info(module) -> None:
    from hermes_cli.version_info_cache import read_head

    real = module._git_version_info
    fields = ("base_version", "derived_version", "distance", "commit", "branch", "source", "dirty",
              "commit_date", "distribution")

    def _git_version_info(repo_dir, *, include_untracked=False):
        if include_untracked or not _active():
            return real(repo_dir, include_untracked=include_untracked)
        repo = os.path.normcase(os.path.realpath(str(repo_dir)))
        head = read_head(repo_dir) if repo == _REPO else None
        if head is None:
            return real(repo_dir, include_untracked=include_untracked)
        recorded = _read(VERSION_FILE)
        if recorded.get("repo") == repo and recorded.get("head") == head.commit:
            try:
                info = module.VersionInfo(**recorded["info"])
                stats["version_hit"] += 1
                return info
            except (KeyError, TypeError):
                pass
        info = real(repo_dir, include_untracked=include_untracked)
        stats["version_miss"] += 1
        _write(VERSION_FILE, {"repo": repo, "head": head.commit,
                              "info": {name: getattr(info, name) for name in fields}})
        return info

    _git_version_info.__wrapped__ = real
    module._git_version_info = _git_version_info


# ── utils.fast_safe_load ─────────────────────────────────────────────────────

_manifests: dict = {}
_manifests_dirty = False


def _hook_utils(module) -> None:
    global _manifests
    real = module.fast_safe_load
    _manifests = _read(MANIFEST_FILE)

    def fast_safe_load(stream):
        global _manifests_dirty
        if not _active():
            return real(stream)
        try:
            path = os.path.normcase(os.path.realpath(stream.name))
            st = os.fstat(stream.fileno())
        except (AttributeError, OSError, TypeError, ValueError):
            return real(stream)
        if not path.startswith(_PLUGINS):
            return real(stream)
        signature = [st.st_mtime_ns, st.st_size]
        entry = _manifests.get(path)
        if isinstance(entry, dict) and entry.get("sig") == signature and "data" in entry:
            stats["manifest_hit"] += 1
            return copy.deepcopy(entry["data"])
        data = real(stream)
        stats["manifest_miss"] += 1
        try:
            if json.loads(json.dumps(data)) == data:
                _manifests[path] = {"sig": signature, "data": copy.deepcopy(data)}
                _manifests_dirty = True
        except (TypeError, ValueError):
            pass
        return data

    fast_safe_load.__wrapped__ = real
    module.fast_safe_load = fast_safe_load


def _flush_manifests(_module=None) -> None:
    global _manifests_dirty
    if _manifests_dirty:
        _manifests_dirty = False
        _write(MANIFEST_FILE, _manifests)


# ── hermes_cli.banner ────────────────────────────────────────────────────────

def _hook_banner(module) -> None:
    real = module._skip_background_prefetch

    def _skip_background_prefetch():
        if _active():
            stats["prefetch_off"] += 1
            return True
        return real()

    module._skip_background_prefetch = _skip_background_prefetch


# ── post-import hook machinery ───────────────────────────────────────────────

class _HookedLoader(importlib.abc.Loader):
    def __init__(self, inner, hook):
        self._inner, self._hook = inner, hook

    def create_module(self, spec):
        return self._inner.create_module(spec)

    def exec_module(self, module):
        self._inner.exec_module(module)
        source = getattr(module, "__file__", None) or ""
        if _active() and os.path.normcase(os.path.realpath(source)).startswith(_REPO + os.sep):
            try:
                self._hook(module)
            except Exception:  # never break the child
                pass

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _AfterImport(importlib.abc.MetaPathFinder):
    def __init__(self, hooks):
        self.hooks = hooks

    def find_spec(self, name, path, target=None):
        hook = self.hooks.get(name)
        if hook is None or not _active():
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(name, path, target)
            if spec is not None:
                break
        else:
            return None
        if spec.loader is not None and hasattr(spec.loader, "exec_module"):
            spec.loader = _HookedLoader(spec.loader, hook)
        return spec


HOOKS = {
    "hermes_cli.version_info": _hook_version_info,
    "utils": _hook_utils,
    "hermes_cli.config": _flush_manifests,
    "hermes_cli.banner": _hook_banner,
}

if os.environ.get(ENV):
    sys.meta_path.insert(0, _AfterImport(HOOKS))
