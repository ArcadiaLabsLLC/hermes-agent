"""An update whose gateway did not restart says so, retries once, and names the one command to run.

Fork-owned (FH-WINDOWS-UPDATE-RESTART-RECEIPT-FALSE-SUCCESS, RULED 2026-11-08). Live on Windows
2026-11-06: a managed source update exited 0 with the receipt's ``restart`` stage ``success``
while its own completion warned that ``gateway_restart`` and ``windows_resume`` did not finish
and no gateway was running. The stage is marked in ``hermes_cli/update_completion.py`` right
after the fleet restart phase, BEFORE the Windows resume and the post-restart verification can
find the gateway owed, and nothing amended it.

The owner's ruling: the update stays a success (contract C3: never a failed update, no
``partial`` outcome, no non-zero exit), but a restart that did not finish is never reported as
done. :func:`settle_owed_restart` runs once, from ``_verify_fleet_after_update`` before the
owed-restart follow-up is written:

- the gateway is owed -> retry the restart once (``hermes gateway restart``'s own command, in a
  fresh interpreter); a restart PROVEN by a new live host-gateway process (or systemd) settles it;
- still owed -> the ``restart`` stage gets a closing ``failed`` mark, the receipt carries the plain
  words (:data:`NOT_RESTARTED`) and the one recourse, and both are printed for the developer.

This path is Developer-edition only (a source checkout updating itself); the packaged Eternia
Harness never self-updates, so the words and the recourse are a developer's.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

#: The receipt's plain words when the gateway did not come back.
NOT_RESTARTED = "Updated — the gateway did not restart"
#: The receipt's words when the one retry brought it back.
RESTARTED_ON_RETRY = "Updated — the gateway restarted on the second try"


class RetryOutcome(str, Enum):
    RESTARTED = "restarted"  # a new gateway process is proven live
    NOT_PROVEN = "not_proven"  # the command ran, nothing proves a gateway serves the new code
    FAILED = "failed"  # the command errored, timed out or exited non-zero


@dataclass(frozen=True, slots=True)
class Settlement:
    outcome: RetryOutcome | None  # None: nothing gateway-side was owed, no retry ran
    summary: str
    recourse: str


def recourse_command(profile: str) -> str:
    """The exact command a developer runs to restart the gateway this update owes."""
    return "hermes gateway restart" if profile in ("", "default") else f"hermes -p {profile} gateway restart"


def _host_gateway_pid() -> int:
    """The live host gateway's pid from its rendezvous record, or 0."""
    from hermes_cli import update_restart_recovery as recovery

    try:
        with open(os.path.join(recovery._host_state_dir(), "host-gateway.json"), encoding="utf-8-sig") as handle:
            record = json.load(handle)
    except (OSError, UnicodeDecodeError, ValueError):
        return 0
    pid = record.get("pid") if isinstance(record, dict) and record.get("role") == "gateway" else None
    return pid if isinstance(pid, int) and pid > 0 and recovery._pid_is_live(pid) else 0


def retry_gateway_restart(profile: str) -> RetryOutcome:
    """Run the recourse once, in a fresh interpreter; RESTARTED only on proof of a NEW process."""
    import subprocess

    from hermes_cli import update_restart_recovery as recovery

    before = _host_gateway_pid()
    if not recovery._run_profile_restart(profile, run=subprocess.run):
        return RetryOutcome.FAILED
    after = _host_gateway_pid()
    if after and after != before:
        return RetryOutcome.RESTARTED
    if recovery._systemd_verified_active(profile, run=subprocess.run):
        return RetryOutcome.RESTARTED
    return RetryOutcome.NOT_PROVEN


def _serve_units(units: Iterable[Any]) -> bool:
    from hermes_cli.update_cmd_fleet_verify import _is_serve_unit

    return any(_is_serve_unit(unit) for unit in units)


def settle_owed_restart(
    restart: Any,
    *,
    gateway_owed: bool,
    stale_serves: Iterable[Any] = (),
    down_serves: Iterable[Any] = (),
    profile: str | None = None,
    retry: Callable[[str], RetryOutcome] | None = None,
    record_stage: Callable[..., None] | None = None,
    record_fact: Callable[[str, Any], None] | None = None,
    say: Callable[[str], None] = print,
) -> Settlement | None:
    """Settle this run's owed restart before the follow-up is written; None when nothing is owed.

    ``restart`` is the fleet restart outcome (``incomplete``, ``failed_or_stale_units``,
    ``stopped_unmapped_pids``). A proven retry with nothing serve-side owed clears
    ``restart.incomplete``, so verification goes on as for a clean restart.
    """
    if not getattr(restart, "incomplete", False):
        return None
    if record_stage is None or record_fact is None:
        from hermes_cli import update_receipt

        record_stage = record_stage or update_receipt.record_stage
        record_fact = record_fact or update_receipt.record_fact
    serve_owed = bool(set(stale_serves) | set(down_serves)) or _serve_units(
        getattr(restart, "failed_or_stale_units", None) or ())
    gateway_owed = gateway_owed or bool(getattr(restart, "stopped_unmapped_pids", None))
    if not gateway_owed:
        # Only serve/dashboard processes are owed: the follow-up names them; the stage is not done.
        record_stage("restart", "failed", owed="serve")
        return Settlement(None, "", "")
    if profile is None:
        from hermes_cli import update_restart_recovery as recovery

        profile = recovery._launch_profile()
    command = recourse_command(profile)
    say(f"  → The gateway did not restart; retrying once: {command}")
    try:
        outcome = (retry or retry_gateway_restart)(profile)
    except Exception:  # health: allow BLE001 -- the code is committed (C3); a failed retry is owed, not raised
        outcome = RetryOutcome.FAILED
    if outcome is RetryOutcome.RESTARTED:
        record_stage("restart", "success", retry=outcome.value)
        record_fact("restart_summary", RESTARTED_ON_RETRY)
        say(f"  ✓ {RESTARTED_ON_RETRY}.")
        if not serve_owed:
            restart.incomplete = False
        return Settlement(outcome, RESTARTED_ON_RETRY, "")
    record_stage("restart", "failed", retry=outcome.value)
    record_fact("restart_summary", NOT_RESTARTED)
    record_fact("restart_recourse", command)
    say(f"  ⚠ {NOT_RESTARTED}. Run: {command}")
    return Settlement(outcome, NOT_RESTARTED, command)
