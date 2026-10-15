"""Explicit request preparation snapshots; authority always uses fresh readers."""
from __future__ import annotations

import copy
from dataclasses import fields
import os
from pathlib import Path
from typing import Any

__layer__ = "stores"


class InstanceReadEpoch:
    """Reuse decoded rows while the request's directory/file identities agree.

    No global cache. Every projection read fingerprints the full directory,
    including file identity, so external writes/retirement invalidate reuse.
    Unknown fingerprints are never cache hits. scan_all remains authoritative.
    """
    def __init__(self):
        self._entry = None
        self._closed = False

    @staticmethod
    def _fingerprint(root):
        try:
            # A new scandir per read observes external changes. DirEntry's
            # enumeration stat avoids 256 extra pathname probes on Windows.
            with os.scandir(root) as entries:
                rows = []
                for entry in entries:
                    name = entry.name.lower() if os.name == "nt" else entry.name
                    if not name.endswith(".json"):
                        continue
                    st = entry.stat()
                    rows.append((entry.name, st.st_dev, st.st_ino, st.st_mtime_ns,
                                 st.st_ctime_ns, st.st_size))
                return tuple(sorted(rows))
        except FileNotFoundError:
            return ()
        except OSError:
            return None

    @staticmethod
    def _copy_scan(scan):
        # PersonaInstance's scalar/date/enum fields are immutable. Copy each
        # row once and recursively copy only its mutable containers; generic
        # deepcopy traverses every scalar through reconstruction machinery.
        from agent_runtime.persona_assignments.scan import PersonaInstanceScan
        instances = []
        names = tuple(field.name for field in fields(scan.instances[0])) if scan.instances else ()
        for row in scan.instances:
            cloned = object.__new__(type(row))
            for name in names:
                value = getattr(row, name)
                if isinstance(value, (dict, list, set, tuple, bytearray)):
                    value = copy.deepcopy(value)
                setattr(cloned, name, value)
            instances.append(cloned)
        return PersonaInstanceScan(instances, scan.unreadable)

    def scan(self, store):
        from agent_runtime import paths
        root = paths.persona_instances_dir().resolve()
        before = self._fingerprint(root)
        key = (str(root), before)
        if not self._closed and before is not None and self._entry is not None and self._entry[0] == key:
            return self._copy_scan(self._entry[1])
        result = store.scan_all()
        after = self._fingerprint(root)
        if not self._closed and before is not None and before == after:
            self._entry = (key, self._copy_scan(result))
        else:
            self.invalidate()
        return result

    def invalidate(self):
        self._entry = None

    def close(self):
        self.invalidate()
        self._closed = True


class SkillPreparationEpoch:
    """One coherent manifest read per candidate during request preparation.

    Callers opt in explicitly; ordinary compatibility/tool authorization never
    consults this snapshot. Close before the provider boundary. New requests
    validate stamps again through the existing parse owner, including replacement.
    """
    def __init__(self):
        self._frontmatter: dict[str, Any] = {}
        self._closed = False

    def frontmatter(self, path: Path):
        from agent_runtime.skill_resolution import _cached_skill_frontmatter
        key = os.path.normcase(str(path.absolute()))
        if self._closed:
            return _cached_skill_frontmatter(path)
        if key not in self._frontmatter:
            self._frontmatter[key] = copy.deepcopy(_cached_skill_frontmatter(path))
        return copy.deepcopy(self._frontmatter[key])

    def invalidate(self):
        self._frontmatter.clear()

    def close(self):
        self.invalidate()
        self._closed = True
