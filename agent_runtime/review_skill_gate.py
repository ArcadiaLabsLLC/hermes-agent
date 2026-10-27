"""The background review never writes a SHARED skill directly (RT-REVIEW-SHARED-SKILL-GATE).

The post-turn skill review (``agent/background_review.py``, upstream) wrote straight into the
account's shared skills folder, which every agent of the account loads: one agent's turn re-wrote
every agent's guidance, with no check, no owner view and no copy of the old text (the owner's Neko
trial, turn ``agent-chat-send-4743c92d-af53-4bbb-ab40-5438eaa74895``).

The eternia-harness plugin's ``pre_tool_call`` hook asks :func:`review_shared_skill_write` before
every tool call. A ``skill_manage`` call made under the ``background_review`` write origin whose
target resolves inside :func:`agent_runtime.profile_home.get_shared_skills_dir` is:

1. **staged** through upstream's own write-approval store (``tools.write_approval.stage_write``,
   the ``skills`` subsystem, ``origin: background_review``) — the same record ``/skills pending``,
   ``/skills diff <id>`` and ``/skills approve <id>`` already read and replay, so approval is the
   check and promotion is upstream's replay, not a second door;
2. **snapshotted**: the package as it stands is copied to ``<shared>/.archive/<skill>-<stamp>-pre-review``
   (resolver-invisible — ``agent.skill_utils.EXCLUDED_SKILL_DIRS``), so the text a later approval
   replaces can be put back;
3. **refused** to the review fork with a message naming the pending id, so it does not retry;
4. **attributed**: the chat and turn the review came from are recorded against the pending id
   (:func:`agent_runtime.review_skill_changes.record_staged`, RT-SKILL-CHANGE-RECORD).

Profile-local skills keep writing directly; a ``create`` lands in the profile's own skills dir and
is never staged. A foreground write (the operator's own turn) is never touched.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__layer__ = "lanes"
__all__ = ["PRE_REVIEW_SUFFIX", "REVIEW_GATED_ACTIONS", "review_shared_skill_write", "write_targets"]

logger = logging.getLogger(__name__)

#: The ``skill_manage`` actions that change an EXISTING package (``create`` writes the profile's dir).
REVIEW_GATED_ACTIONS = frozenset({"edit", "patch", "delete", "write_file", "remove_file"})
PRE_REVIEW_SUFFIX = "pre-review"

#: The ``skill_manage`` keyword arguments a staged record replays (``apply_skill_pending``).
_REPLAY_KEYS = ("action", "name", "content", "category", "file_path", "file_content",
                "old_string", "new_string", "replace_all", "absorbed_into", "operations")


def _shared_package_dir(name: Any, shared_root: Path) -> Path | None:
    from agent_runtime._upstream_doors import skill_manage_target

    if not isinstance(name, str) or not name.strip():
        return None
    try:
        target = skill_manage_target(name.strip())
        if target is None:
            return None
        return target if Path(target).resolve().is_relative_to(shared_root.resolve()) else None
    except Exception:  # an unresolvable name is not a shared write; skill_manage reports it
        return None


def write_targets(args: dict[str, Any]) -> list[tuple[str, str]]:
    """``(action, name)`` of every write a ``skill_manage`` call makes (a batch's operations, or the flat call)."""
    operations = args.get("operations")
    if isinstance(operations, list):
        return [(str(op.get("action") or ""), str(op.get("name") or args.get("name") or ""))
                for op in operations if isinstance(op, dict)]
    return [(str(args.get("action") or ""), str(args.get("name") or ""))]


def _keep_prior_package(package: Path, shared_root: Path) -> Path | None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = shared_root / ".archive" / f"{package.name}-{stamp}-{uuid.uuid4().hex[:6]}-{PRE_REVIEW_SUFFIX}"
    try:
        shutil.copytree(package, destination)
        return destination
    except OSError:
        logger.warning("review skill gate: could not snapshot %s", package, exc_info=True)
        return None


def review_shared_skill_write(tool_name: Any, args: Any) -> dict[str, Any] | None:
    """A ``pre_tool_call`` block directive for a review write to a shared skill, else None."""

    if tool_name != "skill_manage" or not isinstance(args, dict):
        return None
    from tools.skill_provenance import is_background_review

    if not is_background_review():
        return None
    from agent_runtime.profile_home import get_shared_skills_dir

    shared_root = get_shared_skills_dir()
    packages = {
        package for action, name in write_targets(args) if action in REVIEW_GATED_ACTIONS
        for package in [_shared_package_dir(name, shared_root)] if package is not None
    }
    if not packages:
        return None
    from tools import write_approval as wa

    payload = {key: args[key] for key in _REPLAY_KEYS if args.get(key) is not None}
    gist = wa.skill_gist(str(payload.get("action") or "batch"), str(payload.get("name") or ""),
                         **{key: str(payload.get(key) or "")
                            for key in ("content", "file_path", "old_string", "new_string")})
    record = wa.stage_write(wa.SKILLS, payload, summary=f"[shared] {gist}", origin="background_review")
    from agent_runtime.review_skill_changes import record_staged

    record_staged(record["id"], sorted(package.name for package in packages), str(payload.get("action") or "batch"))
    kept = [str(path) for path in (_keep_prior_package(package, shared_root) for package in sorted(packages)) if path]
    logger.info("review_skill_gate staged=%s skills=%s kept=%s", record["id"],
                ",".join(sorted(package.name for package in packages)), len(kept))
    return {"action": "block", "message": (
        f"Staged for the owner as pending skill write {record['id']}: "
        f"{', '.join(sorted(package.name for package in packages))} is a SHARED skill every agent "
        "of this account loads, so the background review does not write it directly. The current "
        f"text is kept ({'; '.join(kept) or 'snapshot failed'}). Do not retry this write; "
        "say in your reply what you proposed and why.")}
