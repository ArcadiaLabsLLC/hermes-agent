"""The default brain — a workspace whose repos carry no brain still has a todo board (plan §4).

``ensure_default_brain`` writes a two-note skeleton under ``paths.default_brain_dir(ws)``, makes
it a git repository with one commit under hermes's own per-machine identity (``-c`` pairs, never
``git config``) and records a MACHINE-LOCAL binding, ``board.binding_path(ws)``
(``{slot, path, brain_dir, default_branch, created_at, machine, remote_url, retired_into}``). It is
not a declared slot in the realm-synced slot document, so it works the same in every realm and
never needs the realm publish right (owner ruling 2026-10-18 on ``RT-WORK-DEFAULT-BRAIN-REALM``).
It starts local-only: no remote, nothing pushed.

When a repo slot with a brain is bound, ``agent_runtime/work/store.py::normalize_default_brain``
moves the open rows into that brain and retires the binding (``retire_binding``).

**Promotion** (``RT-WORK-DEFAULT-BRAIN-REMOTE``, plan ``p10-work-2026-10-19.md`` §2.5; owner ruling
2026-10-18: a connected git account means the remote is created automatically) is the one door from
binding to slot. ``promote_default_brain``: the machine's own GitHub chain answers an account
(``git_host_account.connected_github``) → a PRIVATE ``eternia-work-<slug>`` repo is created (an
existing name is refused ``remote_exists``, never adopted) → ``git_remote_adopt.adopt_remote`` pushes
the brain with upstream → the binding records ``remote_url`` → slot ``brain`` is declared with
``workspace_slots.declare_one_slot`` and bound here where ``require_publish_right(ws, None)`` passes,
else the entry is STAGED in the binding (``declaration.state == "pending"``) for the Launcher's next
credentialed ``slots.declare``. ``ensure_default_brain`` promotes on its own when the machine is
connected; a refusal backs the auto path off for ``PROMOTE_RETRY_S`` (the manual door,
``runtime.work.create_brain`` with ``promote: true``, ignores it). A SECOND machine adopts the declared
slot instead of creating a brain: it clones the remote (``adopt_remote`` into an empty repo), binds
it, and a local default brain's rows move in through ``normalize_default_brain``.
Pinned by ``tests/agent_runtime/work_store/test_default_brain.py``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .. import paths
from ..workspace_slots import (
    REASON_MACHINE_UNIDENTIFIED,
    REASON_REALM_PUBLISH_DENIED,
    SlotRefused,
    bound_path,
    live_slots,
    install_id,
    load_document,
    stamp_epoch,
)
from . import receipts
from .board import (
    DEFAULT_BRAIN_QUEUE_DIR,
    DEFAULT_BRAIN_SLOT,
    Board,
    binding_path,
    declaration_state,
    declared_boards,
    default_board,
    has_brain_here,
    needs_default_brain,
    read_binding,
)
from .reasons import Reason, WorkRefused

__layer__ = "stores"
__all__ = [
    "IDENTITY_PAIRS",
    "PROMOTE_RETRY_S",
    "QUEUE_TEMPLATE",
    "TODO_TEMPLATE",
    "brain_repo_name",
    "ensure_default_brain",
    "promote_default_brain",
    "remote_state",
    "retire_binding",
    "skeleton",
]

#: How long the AUTOMATIC promotion waits after a refusal before trying again (the manual door never waits).
PROMOTE_RETRY_S = 24 * 3600
#: An adopter refusal as a Work refusal.
_ADOPT_REASONS = {"url_mismatch": Reason.URL_MISMATCH, "remote_diverged": Reason.REMOTE_DIVERGED,
                  "fetch_failed": Reason.FETCH_FAILED, "push_failed": Reason.PUSH_REFUSED,
                  "not_a_repo": Reason.NO_BRAIN}

BRAIN_FOLDER = "Work_Brain"
QUEUE_DIR = DEFAULT_BRAIN_QUEUE_DIR
QUEUE_NOTE = "work-queue.md"

TODO_TEMPLATE = """---
type: moc
tags: [moc, work]
---

# TODO

The master pointer list; it holds no rows. This workspace's tasks are the rows of
[[work-queue]] (`20 — Active Initiatives/work-queue.md`).

```dataview
TABLE program, status FROM "Work_Brain/20 — Active Initiatives" WHERE type = "queue"
```
"""

QUEUE_TEMPLATE = """---
type: queue
program: work
status: open
tags: [queue, program/work]
---

# Work queue

Row grammar (Harness_Brain ADR 0011, the launcher's ADR 0025): `- **`<ID>` — <title>** · … · <status>`,
one line, a unique ID, EXACTLY ONE of `READY <date>` / `BLOCKED <date>: <reason> — …` /
`DEFERRED <date>: …` / `NEEDS PLAN <date>: …`; a claim is `**TAKEN <date> <who>**`.
"""

def IDENTITY_PAIRS(machine: str) -> tuple[str, str]:
    """Hermes's own commit identity on this machine, as ``git -c`` pairs (never written to a config)."""

    return ("user.name=Eternia Harness", f"user.email=harness+{machine}@eternia.local")


def skeleton(root: Path) -> list[Path]:
    """Write the two notes under ``root`` (an existing note is left as it is); the paths, TODO first."""

    notes = [(root / BRAIN_FOLDER / "TODO.md", TODO_TEMPLATE), (root / QUEUE_DIR / QUEUE_NOTE, QUEUE_TEMPLATE)]
    for path, text in notes:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(text, encoding="utf-8", newline="\n")
    return [path for path, _ in notes]


def _brain_git(args: list[str], *, root: Path, machine: str, reason: Reason) -> str:
    from ..git_cmd import run_git

    done = run_git(args, repo=root, config=IDENTITY_PAIRS(machine), timeout=60, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise WorkRefused(reason, f"git {args[0]}: {str(done.stderr or '').strip()[-200:]}")
    return str(done.stdout or "")


def _commit_skeleton(root: Path, workspace_id: str, machine: str) -> None:
    """``init`` (once) → ``add -A`` → ``commit`` when anything is staged; no remote, ever."""

    if not (root / ".git").exists():
        _brain_git(["init", "-q", "-b", "main"], root=root, machine=machine, reason=Reason.COMMIT_FAILED)
    _brain_git(["add", "-A"], root=root, machine=machine, reason=Reason.COMMIT_FAILED)
    if _brain_git(["status", "--porcelain"], root=root, machine=machine, reason=Reason.COMMIT_FAILED).strip():
        _brain_git(["commit", "-q", "-m", f"work: default brain for {workspace_id}"], root=root, machine=machine,
             reason=Reason.COMMIT_FAILED)


def this_machine() -> str:
    """This namespace's install id (the commit identity and branch prefix — per namespace, so two namespaces
    on one PC never cut one branch name of a shared clone; RT-MACHINE-ID), refused ``machine_identity_unavailable`` as a Work refusal;
    the one owner of that wrapper (the batch dispatcher, the serve scheduler and ``work.store.writer_for``
    read it). Whether git is shipped is the lanes caller's check."""

    try:
        return install_id()
    except SlotRefused as exc:
        raise WorkRefused(Reason.MACHINE_UNIDENTIFIED, exc.detail or REASON_MACHINE_UNIDENTIFIED) from exc


def _write_binding(workspace_id: str, record: dict[str, Any]) -> None:
    path = binding_path(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def retire_binding(workspace_id: str, *, into: str, at: str, moved: list[str]) -> None:
    """The default brain's rows now live in slot ``into``; the board stops listing it, and Hermes's worktree of
    it is removed (plan work-slot-roots-per-workspace-2026-10-21 W3)."""

    from .writer import checkout_token, remove_worktree

    record = read_binding(workspace_id) or {}
    root = Path(str(record["path"])) if record.get("path") else None
    if root is not None and (root / ".git").exists():
        remove_worktree(paths.work_worktree_dir(workspace_id, DEFAULT_BRAIN_SLOT, checkout_token(root)), repo=root)
    _write_binding(workspace_id, {**record, "retired_into": into, "retired_at": at, "moved": moved})


def brain_repo_name(workspace_id: str) -> str:
    """``eternia-work-<workspace slug>`` (else the workspace's path token), lower-case ``[a-z0-9._-]``, ≤ 100 chars."""

    from ..store import WorkspaceStore

    try:
        slug = str(WorkspaceStore().get(workspace_id).slug or "")
    except Exception:  # a workspace with no record still names its brain
        slug = ""
    token = re.sub(r"[^a-z0-9._-]+", "-", (slug or paths.safe_path_token(workspace_id)).lower()).strip("-.")
    return ("eternia-work-" + (token or "workspace"))[:100]


def _brain_entry(url: str) -> dict[str, Any]:
    return {"name": DEFAULT_BRAIN_SLOT, "repo": {"clone_url": url, "default_branch": "main"},
            "toolchain": {"kind": "brain"},
            "context": {"role": "brain", "files": [], "brain_dir": QUEUE_DIR, "gate": []}}


def _declare_brain_slot(workspace_id: str, url: str, root: Path, issued_at: str) -> dict[str, Any]:
    """Declare slot ``brain`` and bind it here when this machine may publish; else STAGE the entry."""

    from ..workspace_slots import bind, declare_one_slot, require_publish_right

    entry = _brain_entry(url)
    try:
        require_publish_right(workspace_id, None)
    except SlotRefused as refused:
        if refused.reason != REASON_REALM_PUBLISH_DENIED:
            raise
        return {"state": "pending", "slot": entry}
    declare_one_slot(workspace_id, entry, issued_at=issued_at, machine=this_machine())
    bind(workspace_id, DEFAULT_BRAIN_SLOT, str(root), issued_at=issued_at)
    return {"state": "declared"}


def _refuse_promotion(workspace_id: str, reason: Reason, detail: str, *, issued_at: str,
                      back_off: bool) -> WorkRefused:
    if back_off:
        record = read_binding(workspace_id) or {}
        _write_binding(workspace_id, {**record, "promote_refused": {"reason": reason.value, "at": issued_at}})
    receipts.emit("work.brain_promote_refused", workspace_id=workspace_id, reason=reason.value)
    return WorkRefused(reason, detail)


def promote_default_brain(workspace_id: str, *, issued_at: str) -> dict[str, Any]:
    """Give the live default brain a private GitHub remote and declare it as slot ``brain`` (module docstring)."""

    from ..git_host_account import GitHostRefused, connected_github, create_private_repo
    from ..git_remote_adopt import AdoptRefused, adopt_remote

    record = read_binding(workspace_id)
    if record is None or record.get("retired_into"):
        raise WorkRefused(Reason.NO_BRAIN, "no live default brain to promote")
    if record.get("remote_url"):
        return {"outcome": "already", "url": record["remote_url"], "declaration": record.get("declaration")}
    root = Path(str(record["path"]))
    account = connected_github()
    if account is None:
        raise _refuse_promotion(workspace_id, Reason.NEEDS_GIT_ACCOUNT, "no GitHub credential on this machine answers",
                                issued_at=issued_at, back_off=False)
    try:
        url = create_private_repo(account, brain_repo_name(workspace_id))
        adopt_remote(root, url, branch=str(record.get("default_branch") or "main"))
    except GitHostRefused as refused:
        raise _refuse_promotion(workspace_id, refused.reason, refused.detail, issued_at=issued_at,
                                back_off=True) from None
    except AdoptRefused as refused:
        raise _refuse_promotion(workspace_id, _ADOPT_REASONS.get(refused.reason, Reason.PUSH_REFUSED),
                                refused.detail, issued_at=issued_at, back_off=True) from None
    _write_binding(workspace_id, {**record, "remote_url": url, "promoted_at": issued_at,
                                  "remote_owner": account.login, "promote_refused": None})
    declaration = _declare_brain_slot(workspace_id, url, root, issued_at)
    _write_binding(workspace_id, {**(read_binding(workspace_id) or {}), "declaration": declaration})
    receipt = receipts.emit("work.brain_promoted", workspace_id=workspace_id, url=url,
                            declaration=declaration["state"])
    return {"outcome": "promoted", "url": url, "declaration": declaration, "receipt": receipt}


def _refused_recently(record: dict[str, Any]) -> bool:
    at = stamp_epoch((record.get("promote_refused") or {}).get("at"))
    return at is not None and time.time() - at < PROMOTE_RETRY_S


def _auto_promote(workspace_id: str, issued_at: str) -> None:
    """The automatic path: promote when connected and not backing off; a refusal is a receipt, never raised."""

    from ..git_host_account import connected_github

    record = read_binding(workspace_id)
    if record is None or record.get("retired_into") or record.get("remote_url") or _refused_recently(record):
        return
    if connected_github() is None:
        return
    try:
        promote_default_brain(workspace_id, issued_at=issued_at)
    except (WorkRefused, SlotRefused) as refused:
        receipts.emit("work.brain_auto_promote_refused", workspace_id=workspace_id,
                      reason=getattr(refused.reason, "value", refused.reason))


def _settle_pending(workspace_id: str, record: dict[str, Any], issued_at: str) -> None:
    """A staged declaration the Launcher has since declared (same clone URL): bind it here, mark it declared."""

    from ..workspace_slots import bind

    declared = live_slots(load_document(workspace_id)).get(DEFAULT_BRAIN_SLOT) or {}
    url = (declared.get("repo") or {}).get("clone_url")
    if declaration_state(record) != "pending" or not url or url != record.get("remote_url"):
        return
    bind(workspace_id, DEFAULT_BRAIN_SLOT, str(record["path"]), issued_at=issued_at)
    _write_binding(workspace_id, {**record, "declaration": {"state": "declared"}})


def _adopt_declared_brain(workspace_id: str, root: Path, issued_at: str) -> Board | None:
    """A second machine: clone the declared ``brain`` slot's remote instead of creating a brain (None: not here)."""

    from ..git_cmd import run_git
    from ..git_remote_adopt import AdoptRefused, adopt_remote
    from ..workspace_slots import bind

    declared = live_slots(load_document(workspace_id)).get(DEFAULT_BRAIN_SLOT) or {}
    repo = declared.get("repo") or {}
    url, branch = repo.get("clone_url"), str(repo.get("default_branch") or "main")
    here = bound_path(DEFAULT_BRAIN_SLOT, workspace_id=workspace_id)
    if not url or (here is not None and here.is_dir()) or (read_binding(workspace_id) or {}).get("remote_url") == url:
        return None
    target = root if not (root / ".git").exists() else root.with_name("brain-remote")
    target.mkdir(parents=True, exist_ok=True)
    run_git(["init", "-q", "-b", branch], repo=target, timeout=60, stdin=subprocess.DEVNULL)
    try:
        adopt_remote(target, url, branch=branch)
    except AdoptRefused as refused:
        receipts.emit("work.brain_adopt_refused", workspace_id=workspace_id, reason=refused.reason)
        return None
    bind(workspace_id, DEFAULT_BRAIN_SLOT, str(target), issued_at=issued_at)
    receipts.emit("work.brain_adopted", workspace_id=workspace_id, url=url, path=target.name)
    return next((board for board in declared_boards(workspace_id)
                 if board.slot == DEFAULT_BRAIN_SLOT and has_brain_here(board)), None)


def remote_state(workspace_id: str) -> dict[str, Any] | None:
    """The live default brain's remote state for ``capabilities`` (None: nothing to add to the caller's word).

    ``remote`` (declared), ``remote_pending_declare`` (+ ``clone_url``, ``slot``), ``remote_refused``
    (+ ``reason``, ``retry_after``); a local brain on an unconnected machine stays ``present`` (the tree's
    word for the plan's ``local``) with ``reason: needs_git_account``.
    """

    from ..git_host_account import connected_github

    record = read_binding(workspace_id)
    if record is None or record.get("retired_into"):
        return None
    url, state = record.get("remote_url"), declaration_state(record)
    if url and state == "declared":
        return {"state": "remote", "clone_url": url}
    if url and state == "pending":
        return {"state": "remote_pending_declare", "clone_url": url,
                "slot": (record.get("declaration") or {}).get("slot")}
    refused = record.get("promote_refused") or {}
    at = stamp_epoch(refused.get("at"))
    if not url and refused.get("reason") and at is not None:
        retry = datetime.fromtimestamp(at, UTC) + timedelta(seconds=PROMOTE_RETRY_S)
        return {"state": "remote_refused", "reason": refused["reason"],
                "retry_after": retry.isoformat(timespec="seconds")}
    if not url and connected_github() is None:
        return {"state": "present", "reason": Reason.NEEDS_GIT_ACCOUNT.value}
    return None


def ensure_default_brain(workspace_id: str, *, issued_at: str) -> Board:
    """The board a workspace's work lands on, creating the default brain only when it has none.

    A workspace whose declared slots carry a brain bound here gets no default brain; that board is
    returned instead. Idempotent: a live binding returns its board; a retired one (its rows moved
    into a repo brain that is no longer bound here) comes back live and empty.
    """

    found = declared_boards(workspace_id)
    if not needs_default_brain(found):
        return next(board for board in found if has_brain_here(board))
    root = paths.default_brain_dir(workspace_id)
    record = read_binding(workspace_id)
    if record is not None and not record.get("retired_into"):
        _settle_pending(workspace_id, record, issued_at)
    adopted = _adopt_declared_brain(workspace_id, root, issued_at)
    if adopted is not None:
        return adopted
    record = read_binding(workspace_id)
    if record is not None and (root / ".git").exists():
        if record.get("retired_into"):
            _write_binding(workspace_id, {**record, "retired_into": None, "retired_at": None})
        _auto_promote(workspace_id, issued_at)
        return _default(workspace_id)
    machine = this_machine()
    root.mkdir(parents=True, exist_ok=True)
    skeleton(root)
    _commit_skeleton(root, workspace_id, machine)
    _write_binding(workspace_id, {"slot": DEFAULT_BRAIN_SLOT, "path": str(root), "brain_dir": QUEUE_DIR,
                                  "default_branch": "main", "created_at": issued_at, "machine": machine,
                                  "remote_url": None, "retired_into": None})
    _auto_promote(workspace_id, issued_at)
    return _default(workspace_id)


def _default(workspace_id: str) -> Board:
    """The live default board, or — once promoted and declared — the declared slot ``brain`` bound here."""

    board = default_board(workspace_id) or next(
        (found for found in declared_boards(workspace_id)
         if found.slot == DEFAULT_BRAIN_SLOT and has_brain_here(found)), None)
    if board is None:
        raise WorkRefused(Reason.NO_BRAIN, "the default brain's binding did not read back")
    return board
