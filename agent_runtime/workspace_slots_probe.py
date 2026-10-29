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
declared ``repo.clone_url`` (``checkout: matches | remote_mismatch | not_a_repo``; a
``repo.local`` slot with a ``.git`` answers ``local``, no remote check); each
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
from .workspace_slot_recipe import READY_UNKNOWN, READY_YES, readiness
from .workspace_slots import (
    _now_iso,
    bound_path,
    legacy_machine_key,
    live_slots,
    load_document,
    machine_id,
    rekey_legacy_report,
    report_namespace,
    write_document,
)

__layer__ = "stores"

PROBE_SET = "set"
PROBE_MISSING = "missing"
PROBE_UNKNOWN = "unknown"

CHECKOUT_MATCHES = "matches"
CHECKOUT_REMOTE_MISMATCH = "remote_mismatch"
CHECKOUT_NOT_A_REPO = "not_a_repo"
#: A ``repo.local`` slot (the Work default brain) is a repository with no remote to match.
CHECKOUT_LOCAL = "local"

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


def origin_matches(path: Path, slot: dict[str, Any], run: Runner | None = None) -> bool:
    """True when the checkout at ``path`` has an ``origin`` matching the slot's declared ``repo.clone_url``."""

    wanted = str((slot.get("repo") or {}).get("clone_url") or "")
    if not wanted:
        return False
    try:
        done = (run or _run)(["git", "-C", str(path), "remote", "get-url", "origin"])
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and _normalize_remote(done.stdout) == _normalize_remote(wanted)


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
        if (self.slot.get("repo") or {}).get("local") is True:
            return CHECKOUT_LOCAL
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
        row["status"] = _status(self.name, row, self.slot)
        row["unknowns"] = self.unknowns.wire()
        return row


def _status(name: str, row: dict[str, Any], slot: dict[str, Any]) -> str:
    """The row's status, from THE readiness answer (``workspace_slot_recipe.readiness``).

    One authority for "ready on this machine": any unknown probe ⇒ ``unknown``; a required
    piece missing, a checkout that is not a repository, or a remote that does not match the
    declaration ⇒ ``needs_setup``; else ``ready``.
    """

    ready = readiness(name, slot, row)["ready"]
    return STATUS_READY if ready == READY_YES else STATUS_UNKNOWN if ready == READY_UNKNOWN else STATUS_NEEDS_SETUP


def report(
    workspace_id: str, *, run: Runner | None = None, now: float | None = None, fresh_binds: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Re-probe every declared slot, write ``machines.<me>``, and answer it.

    A slot found bound on its FIRST report that this call did not just bind (``fresh_binds``)
    was a machine root before the workspace declared its name: it is adopted as the fill and
    the row says so, ``adopted_existing_root: true`` (call 8g).
    """

    document = load_document(workspace_id)
    entry, me = _probe_into(document, lambda name: slot_fill(workspace_id, name),
                            lambda name: bound_path(name, workspace_id=workspace_id),
                            run=run, now=now, fresh_binds=fresh_binds)
    write_document(workspace_id, document)
    return {"machine": me, **entry}


def report_project(
    project_id: str, *, run: Runner | None = None, now: float | None = None, fresh_binds: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """:func:`report` for a Project's slots: ``machines.<me>`` of the Project record (plan §3)."""

    from .project_store import load_project, write_project

    record = load_project(project_id)
    entry, me = _probe_into(record, lambda name: slot_fill(None, name, project_id=project_id),
                            lambda name: bound_path(name, project_id=project_id),
                            run=run, now=now, fresh_binds=fresh_binds)
    record["project_id"] = project_id
    write_project(project_id, record)
    return {"machine": me, **entry}


def _probe_into(document: dict[str, Any], fill_for: Callable[[str], SlotFill | None],
                bound_for: Callable[[str], Path | None], *, run: Runner | None, now: float | None,
                fresh_binds: frozenset[str]) -> tuple[dict[str, Any], str]:
    """Probe every live slot of ``document`` and set its ``machines.<me>``; ``(entry, me)``."""

    import time

    me = machine_id()
    rekey_legacy_report(document, me, legacy_machine_key())
    previous = ((document.get("machines") or {}).get(me) or {}).get("slots") or {}
    stamp = time.time() if now is None else now
    slots = {}
    for name, slot in live_slots(document).items():
        row = _SlotProbe(name, slot, fill_for(name), run or _run, stamp).row(bound_for(name))
        if row["bound"] and name not in previous and name not in fresh_binds:
            row["adopted_existing_root"] = True
        slots[name] = row
    entry = {"reported_at": _now_iso(), "namespace": report_namespace(), "slots": slots}
    document.setdefault("machines", {})[me] = entry
    return entry, me
