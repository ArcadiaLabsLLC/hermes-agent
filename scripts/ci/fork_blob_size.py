#!/usr/bin/env python3
"""The fork's blob-size guard: upstream's check, with the phone wheels the fork commits also exempt.

Fork-owned (row FH-THE-BLOB-SIZE-GUARD-ACCEPTS-THE-COMMITTED-MATCHER-WHEELS, owner RULED 2026-11-22,
option (a)). Upstream's ``scripts/ci/check_blob_size.py`` reds a change that adds a binary over 500 KiB
unless ``.github/blob-size-allowlist.txt`` names it. The fork commits ripgrep's matcher wheels for
Android under ``crates/project_files_match/dist/`` (~0.9 MB each; owner RULED 2026-11-21, row
RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID: "yea commit them to the hermes fork which is public"), and both
upstream files keep upstream's bytes: the upstream footprint never rises (``tests/scripts/
test_upstream_footprint.py``; adding the paths there was tried and reverted, ce200e1767).

So this wrapper runs upstream's ``find_offenders`` with upstream's allowlist PLUS the fork's: every wheel
``agent_runtime/bundle_profiles/phone_wheels.lock.json`` pins by repo-relative ``path`` (a committed
wheel; a ``url`` pin is downloaded and never in git). The lock is the one place those paths live — the
packager installs from it — so a new pair (the iPhone's, a crate bump) is exempt the moment it is pinned
and nothing else is. Both lists are read from the judged side, as upstream reads its own.

The fork runs this, never upstream's script: ``scripts/prepush.sh`` (step ``blob-size``, the pushed
commits) and ``.github/workflows/fork-gates.yml`` (job ``blob-size``). Upstream's own step in
``repo-guards.yml`` still judges with upstream's list alone; it runs only where the fork's upstream CI
runs (disabled on the fork since 2026-09-26), and would red a commit that adds or rebuilds a wheel.

    python scripts/ci/fork_blob_size.py                    # working tree vs merge-base with origin/main
    python scripts/ci/fork_blob_size.py --base A --head B  # any two revisions

Exit codes: 0 = nothing over the limit, 1 = at least one offender, 2 = git, lock or usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_blob_size as upstream

PHONE_WHEELS_LOCK = "agent_runtime/bundle_profiles/phone_wheels.lock.json"


def committed_wheel_paths(lock: dict) -> set[str]:
    """Every repo-relative ``path`` pin in the phone wheels lock: the wheels the fork commits."""
    # MUTATION: drop one pin here (the x86_64 wheel's) and test_the_pinned_wheels_pass_where_upstreams_guard_alone_reds,
    # test_a_big_blob_on_no_list_is_red_beside_the_exempt_wheels and
    # test_every_wheel_committed_under_the_crate_is_exempt_through_the_lock redden (recorded 2026-11-22).
    return {pin["path"] for entry in lock.get("wheels", {}).values()
            for pin in entry.get("targets", {}).values() if "path" in pin}


def _lock_text(repo: Path, head: str | None) -> str | None:
    if head is None:
        disk = repo / PHONE_WHEELS_LOCK
        return disk.read_text(encoding="utf-8") if disk.is_file() else None
    proc = subprocess.run(["git", "cat-file", "blob", f"{head}:{PHONE_WHEELS_LOCK}"], cwd=repo,
                          capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL,
                          timeout=60, check=False)
    return proc.stdout if proc.returncode == 0 else None


def fork_allowlist(repo: Path, head: str | None) -> set[str]:
    """The committed wheels the judged side (revision ``head``, else the working tree) pins."""
    text = _lock_text(repo, head)
    if text is None:
        return set()
    try:
        return committed_wheel_paths(json.loads(text))
    except (ValueError, AttributeError, KeyError, TypeError) as exc:
        raise upstream.GitError(f"{PHONE_WHEELS_LOCK} is unreadable: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base", help="base revision (default: merge-base with origin/main)")
    parser.add_argument("--head", help="head revision or tree (default: the working tree)")
    parser.add_argument("--limit", type=int, default=upstream.MAX_BYTES,
                        help=f"bytes (default {upstream.MAX_BYTES})")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    try:
        base = args.base or upstream.default_base(repo, args.head)
        allowlist = (upstream.allowlist_at(repo, args.head) if args.head
                     else upstream.read_allowlist(repo / upstream.ALLOWLIST))
        allowlist |= fork_allowlist(repo, args.head)
        # MUTATION: exempt the crate's dist/ directory instead of the pinned paths (or report no offender)
        # and test_a_committed_wheel_the_lock_does_not_pin_is_red, test_a_big_blob_on_no_list_is_red_beside_
        # the_exempt_wheels and test_the_lists_are_read_from_the_judged_side redden (recorded 2026-11-22).
        offenders = upstream.find_offenders(repo, base, args.head, args.limit, allowlist)
    except upstream.GitError as exc:
        print(f"fork_blob_size: {exc}", file=sys.stderr)
        return 2
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(upstream.summary_table(offenders, args.limit))
    if not offenders:
        print(f"fork_blob_size: no added or modified file over {args.limit // 1024} KiB "
              "(upstream's allowlist and the phone wheels lock's committed wheels exempt)")
        return 0
    print("\n".join(upstream.render(offenders, args.limit)))
    print(f"  - the fork: a phone wheel the owner ruled is committed is pinned by `path` in {PHONE_WHEELS_LOCK};"
          "\n    never edit upstream's allowlist. Reproduce: python scripts/ci/fork_blob_size.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
