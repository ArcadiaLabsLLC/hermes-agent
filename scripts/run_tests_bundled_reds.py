"""Known reds the landing gate does not re-run (fork-hygiene row, owner 2026-10-16).

A known red (red or timed out in the last recorded run, ``run_tests_bundled_plan``)
used to run once, alone, on every gate: on the Phase B gate 24 of them cost
Σ 2,958 s re-proving reds already on ``main``. Now each red outcome writes the
file's dependency KEY (``run_tests_bundled_cache.Keyer``, the same record and key
the green-result cache uses) to ``<store>/red.jsonl``; the next run skips a known
red whose key is unchanged and reports it red as ``known-red, skipped``.

A skip can only ever keep a red red, never make one green: the cost of a missed
dependency is a stale red, bounded by the store generation and the green cache's
max age. A named file, ``--rerun-known-reds``, a disabled cache and a dry run
skip nothing.

Pure like ``run_tests_bundled_cache``: the gate wires it in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import run_tests_bundled_cache as cache  # registered by run_tests_bundled._load_sibling
import run_tests_bundled_via as vias

RED_FILE = "red.jsonl"
#: ``FileOutcome.via`` of a known red reported without a process
SKIPPED_VIA = vias.KNOWN_RED_SKIPPED


def red_path(store: cache.GateStore) -> Path:
    return store.root / RED_FILE


def load(store: cache.GateStore) -> dict[str, dict]:
    """rel → its newest ``red.jsonl`` line (a later line supersedes)."""

    return {r["f"]: r for r in cache._read_jsonl(red_path(store)) if r.get("f")}


def write_key(store: cache.GateStore, rel: str, key: str, run_id: str, generation: int,
              now: Optional[float] = None) -> None:
    now = time.time() if now is None else now
    cache._append_lines(red_path(store), [{
        "f": rel, "key": key, "run": run_id, "t": time.strftime("%Y-%m-%d", time.localtime(now)),
        "epoch": round(now, 1), "gen": generation,
    }])


def drop(store: cache.GateStore, rel: str, why: str, run_id: str) -> None:
    """Supersede a file's red key: it runs next time it is a known red."""

    cache._append_lines(red_path(store), [{"f": rel, "drop": why, "run": run_id}])


def compact(store: cache.GateStore, limit: int = cache.COMPACT_BYTES) -> bool:
    path = red_path(store)
    if cache._size(path) <= limit:
        return False
    cache._rewrite(path, load(store).values())
    return True


@dataclass
class RedDecision:
    """Per known red in the selection: skipped (key unchanged since its red) or run, and why."""

    skipped: list[tuple[Path, dict]] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)

    def line(self) -> str:
        runs = sorted({why for why in self.reasons.values() if why != "unchanged"})
        ran = sum(1 for why in self.reasons.values() if why != "unchanged")
        why = ", ".join(f"{w} {sum(1 for r in self.reasons.values() if r == w)}" for w in runs) or "none"
        return (f"Known reds: {len(self.skipped)} of {len(self.reasons)} skipped (file and recorded dependencies "
                f"unchanged since their red; --rerun-known-reds runs them); {ran} run ({why})")


def decide(
    files: Sequence[Path], repo_root: Path, *, keyer: Optional[cache.Keyer], known: Iterable[str],
    deps: Mapping[str, cache.StoredDeps], reds: Mapping[str, dict], generation: int,
    named: Iterable[Path] = (), now: Optional[float] = None, max_age_days: float = cache.DEFAULT_MAX_AGE_DAYS,
) -> RedDecision:
    """A known red is skipped when it is not named and its newest red line carries
    a key, of this generation, younger than ``max_age_days``, equal to its stored
    dependency record's key against this run's tree."""

    now = time.time() if now is None else now
    known = set(known)
    named_real = {Path(p).resolve() for p in named}
    out = RedDecision()
    for path in files:
        rel = cache.rel_of(path, repo_root)
        if rel not in known:
            continue
        line = reds.get(rel) or {}
        stored = deps.get(rel)
        if keyer is None:
            reason = "no keys"
        elif Path(path).resolve() in named_real:
            reason = "named"
        elif not line.get("key"):
            reason = str(line.get("drop") or "no-red-key")
        elif int(line.get("gen") or 0) < generation:
            reason = "generation"
        elif now - float(line.get("epoch") or 0.0) > max_age_days * 86400:
            reason = "max-age"
        elif stored is None:
            reason = "no-deps"
        elif keyer.key_stored(stored) != line["key"]:
            reason = "changed"
        else:
            reason = "unchanged"
        out.reasons[rel] = reason
        if reason == "unchanged":
            out.skipped.append((path, line))
    return out


def note(line: Mapping, ids: Sequence[str]) -> str:
    """The skipped red's output: why it did not run, and the failing ids the record carries."""

    ids = list(ids)
    head = (f"known red, skipped: the file and its recorded dependencies are unchanged since its red "
            f"{line.get('t', '?')} (run {line.get('run', '?')}); not run. --rerun-known-reds runs it.")
    shown = [f"  red then: {nodeid}" for nodeid in ids[:20]]
    if len(ids) > 20:
        shown.append(f"  … and {len(ids) - 20} more")
    return "\n".join([head] + (shown or ["  red then: (timed out, no failing ids)"]))
