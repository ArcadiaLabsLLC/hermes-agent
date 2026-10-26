"""Home maintenance keyed on the CODE, not the commit (RT-VAULT-COMMIT-HOME-MAINTENANCE).

``hermes_cli/boot_bootstrap.py`` (upstream) runs its home-maintenance steps
once per installed revision, and a revision is a commit. On 2026-10-25 a
fast-forward of three vault-only commits made the next CLI log ``home
maintenance: code changed to 4053e64a90ec, running steps`` while the serve,
keyed on the code tree that excludes ``Harness_Brain/``, rightly did not
restart. :func:`carry_identity_if_code_unchanged` is the fork seam
``run_boot_bootstrap`` calls before its lock: when the recorded revision and
the new one load the same code (``agent_runtime.build_identity.code_tree_unchanged``)
and every recorded step succeeded, the record is re-stamped with the new
revision and the steps are skipped. A failed step, a sealed tree (no
``.git``) or any unanswerable comparison keeps upstream's path.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

__layer__ = "stores"

logger = logging.getLogger(__name__)

CARRIED_FROM_KEY = "carriedFrom"


def _all_steps_succeeded(results: Any) -> bool:
    if not isinstance(results, dict):
        return False
    return all(not (isinstance(r, dict) and r.get("ok") is False) for r in results.values())


def carry_identity_if_code_unchanged(project_root: Path, record: Path, identity: str) -> bool:
    """Re-stamp *record* with *identity* when its revision loads the same code. Never raises."""

    try:
        if not (Path(project_root) / ".git").exists():
            return False
        try:
            known = json.loads(Path(record).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return False
        if not isinstance(known, dict):
            return False
        previous = known.get("identity")
        if not previous or previous == identity or not _all_steps_succeeded(known.get("results")):
            return False
        from agent_runtime.build_identity import code_tree_unchanged

        if not code_tree_unchanged(project_root, previous, identity):
            return False
        payload = {**known, "identity": identity, CARRIED_FROM_KEY: previous}
        tmp = Path(record).with_name(Path(record).name + ".carry.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, record)
        logger.info(
            "home maintenance: code unchanged %s -> %s (code tree equal), steps skipped",
            str(previous)[:12],
            str(identity)[:12],
        )
        return True
    except Exception as exc:
        logger.debug("home maintenance carry skipped: %s", exc)
        return False


__all__ = ["CARRIED_FROM_KEY", "carry_identity_if_code_unchanged"]
