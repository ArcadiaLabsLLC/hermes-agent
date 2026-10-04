"""The slot ACCOUNTING: what this machine reports about its own fill of each slot (§3.2).

``report(workspace_id)`` probes every declared slot on THIS machine and writes the answer to
the slot document's ``machines.<id>`` block — on bind, on serve boot, on
``runtime.workspace.slots.report`` and after an env ``set``. Every probe answers
``set | missing | unknown``; a probe that cannot answer (an unreadable file, a tool that
hangs on ``--version``, git that will not run) is ``unknown`` WITH the evidence on the row
(``slot_probe_unknown``: the probe and its error class). **The report never carries a value
and never a path** — statuses and versions only; the test greps the written document for
every value the fixture environment set.

The probes, in order: the bound path exists and ``git remote get-url origin`` matches the
declared ``repo.clone_url`` (``checkout: matches | remote_mismatch | not_a_repo``); each
declared tool resolves (``tool_paths`` first, then ``PATH`` with the fill's
``path_prepend`` in front, through ``hermes_platform.resolver.locate_command``) and its
``--version`` is parsed where it prints one; each env key is present in the fill's ``env``
or this process's environment; the ``.env`` file is present and each declared key appears
in it (``KEY=`` parsed, value discarded).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from .builds.unknowns import UNKNOWN_SLOT_PROBE_UNKNOWN, UnknownsIndex
from .workspace_slot_env import SlotFill, slot_fill
from .workspace_slots import _now_iso, bound_path, live_slots, load_document, machine_id, write_document

__layer__ = "stores"

PROBE_SET = "set"
PROBE_MISSING = "missing"
PROBE_UNKNOWN = "unknown"

CHECKOUT_MATCHES = "matches"
CHECKOUT_REMOTE_MISMATCH = "remote_mismatch"
CHECKOUT_NOT_A_REPO = "not_a_repo"

STATUS_READY = "ready"
STATUS_NEEDS_SETUP = "needs_setup"
STATUS_NOT_CLONED = "not_cloned"
STATUS_PATH_MISSING = "path_missing"
STATUS_UNKNOWN = "unknown"

#: Seconds a ``--version`` or ``git remote`` probe may take before it is ``unknown``.
PROBE_TIMEOUT_SECONDS = 10.0
_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")
_DOTENV_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")

Runner = Callable[..., subprocess.CompletedProcess]


def _run(argv: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS,
                          stdin=subprocess.DEVNULL, check=False)


def _normalize_remote(url: str) -> str:
    text = url.strip().rstrip("/")
    text = text[:-4] if text.lower().endswith(".git") else text
    text = re.sub(r"^[\w.-]+@([\w.-]+):", r"ssh://\1/", text)
    text = re.sub(r"^(https?|ssh)://[^@/]+@", r"\1://", text)
    return text.lower().split("://", 1)[-1]


class _SlotProbe:
    """One slot's probes on this machine; collects the row and the unknowns."""

    def __init__(self, name: str, slot: dict[str, Any], fill: SlotFill | None, run: Runner, now: float) -> None:
        self.name, self.slot, self.fill, self.run, self.now = name, slot, fill or SlotFill(), run, now
        self.unknowns = UnknownsIndex()

    def unknown(self, probe: str, exc: BaseException | str) -> str:
        evidence = f"{self.name}: {probe}: {exc if isinstance(exc, str) else type(exc).__name__}"
        self.unknowns.add(UNKNOWN_SLOT_PROBE_UNKNOWN, evidence, self.now)
        return PROBE_UNKNOWN

    def checkout(self, path: Path) -> str:
        if not (path / ".git").exists():
            return CHECKOUT_NOT_A_REPO
        try:
            done = self.run(["git", "-C", str(path), "remote", "get-url", "origin"])
        except (OSError, subprocess.SubprocessError) as exc:
            return self.unknown("git remote get-url origin", exc)
        if done.returncode != 0:
            # A directory git does not recognise is not a checkout; a checkout with no
            # ``origin`` is a repository that does not match the declaration.
            return CHECKOUT_NOT_A_REPO if "not a git repository" in str(done.stderr).lower() else CHECKOUT_REMOTE_MISMATCH
        wanted = _normalize_remote(str((self.slot.get("repo") or {}).get("clone_url") or ""))
        return CHECKOUT_MATCHES if _normalize_remote(done.stdout) == wanted else CHECKOUT_REMOTE_MISMATCH

    def tool(self, tool: dict[str, Any]) -> dict[str, Any]:
        from hermes_platform.resolver import locate_command
        from hermes_platform.resolver.core import LookupContext

        name = str(tool.get("name"))
        explicit = self.fill.tool_paths.get(name)
        search = os.pathsep.join([*self.fill.path_prepend, os.environ.get("PATH", "")])
        resolution = locate_command(explicit or name, LookupContext(path=search))
        if not resolution.found:
            return {"status": PROBE_MISSING, "version": None}
        try:
            done = self.run([resolution.command[0], "--version"])
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": self.unknown(f"{name} --version", exc), "version": None}
        match = _VERSION_RE.search(f"{done.stdout}\n{done.stderr}")
        return {"status": PROBE_SET, "version": match.group(1) if match else None}

    def env_keys(self) -> dict[str, str]:
        rows = (self.slot.get("toolchain") or {}).get("env_keys") or []
        present = set(self.fill.env) | set(os.environ)
        return {row["key"]: PROBE_SET if row["key"] in present else PROBE_MISSING for row in rows}

    def dotenv(self, path: Path) -> dict[str, Any] | None:
        declared = (self.slot.get("toolchain") or {}).get("dotenv")
        if not declared:
            return None
        target = path / (self.fill.dotenv or declared.get("path") or ".env")
        if not target.is_file():
            return {"present": False, "keys": {row["key"]: PROBE_MISSING for row in declared.get("keys") or []}}
        try:
            found = {m.group(1) for m in map(_DOTENV_KEY_RE.match, target.read_text(encoding="utf-8").splitlines()) if m}
        except (OSError, UnicodeDecodeError) as exc:
            status = self.unknown(".env read", exc)
            return {"present": True, "keys": {row["key"]: status for row in declared.get("keys") or []}}
        return {"present": True, "keys": {row["key"]: PROBE_SET if row["key"] in found else PROBE_MISSING
                                          for row in declared.get("keys") or []}}

    def row(self, path: Path | None) -> dict[str, Any]:
        if path is None:
            return {"status": STATUS_NOT_CLONED, "bound": False, "unknowns": []}
        if not path.is_dir():
            return {"status": STATUS_PATH_MISSING, "bound": True, "unknowns": []}
        row = {
            "bound": True,
            "checkout": self.checkout(path),
            "tools": {str(t.get("name")): self.tool(t) for t in (self.slot.get("toolchain") or {}).get("tools") or []},
            "env_keys": self.env_keys(),
            "dotenv": self.dotenv(path),
        }
        row["status"] = _status(row, self.slot)
        row["unknowns"] = self.unknowns.wire()
        return row


def _required_missing(row: dict[str, Any], slot: dict[str, Any]) -> bool:
    toolchain = slot.get("toolchain") or {}
    required_env = {r["key"] for r in toolchain.get("env_keys") or [] if r.get("required")}
    required_dotenv = {r["key"] for r in (toolchain.get("dotenv") or {}).get("keys") or [] if r.get("required")}
    dotenv = row.get("dotenv") or {"keys": {}}
    return (any(t["status"] == PROBE_MISSING for t in row["tools"].values())
            or any(row["env_keys"].get(k) == PROBE_MISSING for k in required_env)
            or any(dotenv["keys"].get(k) == PROBE_MISSING for k in required_dotenv))


def _status(row: dict[str, Any], slot: dict[str, Any]) -> str:
    statuses = [t["status"] for t in row["tools"].values()] + list(row["env_keys"].values())
    statuses += list((row.get("dotenv") or {"keys": {}})["keys"].values())
    if PROBE_UNKNOWN in statuses:
        return STATUS_UNKNOWN
    if _required_missing(row, slot) or row["checkout"] == CHECKOUT_NOT_A_REPO:
        return STATUS_NEEDS_SETUP
    return STATUS_READY


def report(
    workspace_id: str, *, run: Runner | None = None, now: float | None = None, fresh_binds: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Re-probe every declared slot, write ``machines.<me>``, and answer it.

    A slot found bound on its FIRST report that this call did not just bind (``fresh_binds``)
    was a machine root before the workspace declared its name: it is adopted as the fill and
    the row says so, ``adopted_existing_root: true`` (call 8g).
    """

    import time

    me = machine_id()
    document = load_document(workspace_id)
    previous = ((document.get("machines") or {}).get(me) or {}).get("slots") or {}
    stamp = time.time() if now is None else now
    slots = {}
    for name, slot in live_slots(document).items():
        row = _SlotProbe(name, slot, slot_fill(workspace_id, name), run or _run, stamp).row(bound_path(name))
        if row["bound"] and name not in previous and name not in fresh_binds:
            row["adopted_existing_root"] = True
        slots[name] = row
    entry = {"reported_at": _now_iso(), "slots": slots}
    document.setdefault("machines", {})[me] = entry
    write_document(workspace_id, document)
    return {"machine": me, **entry}
