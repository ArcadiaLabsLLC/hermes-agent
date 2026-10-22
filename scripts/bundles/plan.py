"""Phase 2 of the packager, the plan: what a bundle ships, first- and third-party.

Split out of ``scripts/bundle_profile_package.py`` (W0-G1 size ceiling, row RT-PACKAGER-CEILING-800).
The static import walk of ``scripts/bundle_profile_closure.py`` plus the pinned modules' own
module-level first-party imports; every third-party import resolved to its distribution by ONE
planning child interpreter over one walk (:func:`distribution_plans`).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.bundle_profiles.forced_tree import sibling_modules
from scripts.bundle_profile_closure import ROOT, _imports, _owner, profile_walk
from scripts.bundles.bundle_files import read_site
from scripts.bundles.targets import marker_env


@dataclass
class Plan:
    profile: str
    target: str
    python_version: str
    first_party: set[str]  # dotted first-party modules shipped
    pinned: set[str]  # switched-off modules shipped because kept code imports them unguarded
    distributions: set[str]  # normalized names: the closure's "needed" set
    missing: set[str] = field(default_factory=set)  # needed, but the site does not hold it
    refusals: list[str] = field(default_factory=list)  # the closure's own packaging refusals
    #: the ``pinned`` modules shipped under ``<bundle>/phone_forced/`` instead of ``app/``
    #: (``packaging.forced_sibling_tree``; :mod:`agent_runtime.bundle_profiles.forced_tree`)
    sibling: set[str] = field(default_factory=set)


def _eager_first_party_closure(start: set[str], index: dict[str, Path]) -> set[str]:
    """Modules loaded by importing ``start``: follow MODULE-LEVEL first-party imports only."""
    done: set[str] = set()
    queue = deque(m for m in start if m in index)
    while queue:
        module = queue.popleft()
        if module in done:
            continue
        done.add(module)
        # Importing a.b.c runs a/__init__ and a/b/__init__ first.
        parts = module.split(".")
        queue.extend(p for p in (".".join(parts[:i]) for i in range(1, len(parts)))
                     if p in index and p not in done)
        path = index[module]
        for dotted, eager, _guarded, _line in _imports(path, module, path.name == "__init__.py"):
            owner = _owner(dotted, index)
            if eager and owner and owner not in done:
                queue.append(owner)
    return done


def _with_parents(modules: set[str], index: dict[str, Path]) -> set[str]:
    out = set(modules)
    for module in modules:
        parts = module.split(".")
        out.update(p for p in (".".join(parts[:i]) for i in range(1, len(parts))) if p in index)
    return out


def first_party_plan(manifest, index: dict[str, Path] | None = None) -> tuple[set[str], set[str], dict]:
    """-> (modules to ship, switched-off modules shipped anyway, the index).

    The closure's own walk (:func:`profile_walk`) keeps what the roots and
    bundled plugins reach. A switched-off module is shipped too when kept code
    imports it UNGUARDED — at module level (``pinned``) or lazily
    (``unguarded_into_pruned``): omitting it turns that line into a runtime
    ImportError, so the feature stays off by its switch and its code ships.
    Each shipped module brings the modules it imports at module level.
    """
    # ``parents``: every kept module's enclosing packages are shipped, and importing the module
    # RUNS their ``__init__`` — so the walk must follow those imports too. Without it
    # ``tools/agent_chat/__init__`` (``from . import detached, schemas, send``) shipped while the
    # siblings it imports did not, and ``agent_runtime.serve_rpc`` failed to import in the bundle.
    result, index = profile_walk(manifest, index, parents=True)
    loaded = forced_modules(result, index)
    return _with_parents(result.kept | loaded, index), loaded, index


def forced_modules(walk, index: dict[str, Path]) -> set[str]:
    """The switched-off modules a walk's kept code forces into the bundle (see :func:`first_party_plan`)."""
    forced = set(walk.pinned) | {row["target"] for row in walk.unguarded_into_pruned}
    return _eager_first_party_closure(forced, index) - walk.kept


def forced_tree_plan(manifest, first_party: set[str], pinned: set[str]) -> set[str]:
    """The forced modules the profile ships in the sibling tree (empty unless it asks for one)."""
    if not getattr(manifest, "packaging_forced_sibling_tree", False):
        return set()
    return sibling_modules(pinned, first_party - pinned)


#: The selection key of the core bundle itself (its own extras, no engine pack).
CORE = ""
#: The planning child reports progress (its step and its parse count) every
#: :data:`PROGRESS_INTERVAL_SECONDS`; it is stopped when that report has not changed for
#: :data:`PLAN_STALL_SECONDS` (counted from its FIRST report: interpreter start-up on a loaded box is
#: not standing still), or when it has run :data:`PLAN_TIMEOUT_SECONDS` in all. Both stops
#: are RETRYABLE (exit :data:`EXIT_RETRYABLE`): a slow child on a busy machine still parses, so it
#: is never stopped for being slow, only for standing still. Sized from the 2026-10-16
#: measurement in ``docs/agent-runtime-harness/04-boot-and-lifecycle.md`` (the bundled-desktop build).
PROGRESS_INTERVAL_SECONDS = 5
PLAN_STALL_SECONDS = 300
PLAN_TIMEOUT_SECONDS = 1800
#: ``EX_TEMPFAIL``: the build did not fail on its inputs; the same inputs may pass on a quieter box.
EXIT_RETRYABLE = 75


class PlanStalled(RuntimeError):
    """The planning child stood still (or ran past its cap): retryable, never a verdict on the inputs."""


_DISTRIBUTION_DRIVER = r"""
import json, sys, threading, time
root, jobs, profile, env, interval = (sys.argv[1], json.loads(sys.argv[2]), sys.argv[3], json.loads(sys.argv[4]),
                                      float(sys.argv[5]))
base_path = list(sys.path)
sys.path[:0] = [*jobs[0]["sites"], root]
import scripts.bundle_profile_closure as closure_script
from agent_runtime.bundle_profiles.manifest import load_profile
closure_script.TARGET_ENV.clear()
closure_script.TARGET_ENV.update(env)
step = ["walk"]
def beat():
    while True:
        print(f"progress {step[0]} parses={closure_script.COUNTS['parses']}", file=sys.stderr, flush=True)
        time.sleep(interval)
threading.Thread(target=beat, daemon=True).start()
out = closure_script.plan_jobs(load_profile(profile, validate=False), jobs, closure_script.TARGET_ENV, root=root,
                               base_path=base_path, progress=lambda name: step.__setitem__(0, name))
print(json.dumps({"jobs": out, "counts": closure_script.COUNTS}))
"""


def _run_planner(cmd: list[str], stall: float, cap: float) -> str:
    """Run the planning child; stdout on success. :class:`PlanStalled` when its progress report
    stops changing for ``stall`` seconds (from its first one) or it runs ``cap`` seconds;
    CalledProcessError on a crash."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                            stdin=subprocess.DEVNULL)
    seen = {"token": None, "at": None}  # the stall clock starts at the first progress line
    tail: deque[str] = deque(maxlen=40)
    out: list[str] = []

    def read_err() -> None:
        for line in proc.stderr:
            line = line.rstrip("\n")
            if line.startswith("progress "):
                if line != seen["token"]:
                    seen["token"], seen["at"] = line, time.monotonic()
            else:
                tail.append(line)

    readers = [threading.Thread(target=read_err, daemon=True),
               threading.Thread(target=lambda: out.append(proc.stdout.read()), daemon=True)]
    for reader in readers:
        reader.start()
    started = time.monotonic()
    while proc.poll() is None:
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        now = time.monotonic()
        stalled = seen["at"] is not None and now - seen["at"] > stall
        why = (f"no progress for {stall:.0f}s (last: {seen['token']})" if stalled else
               f"ran past its {cap:.0f}s cap (last: {seen['token']})" if now - started > cap else None)
        if why and proc.poll() is None:
            proc.kill()
            proc.wait()
            raise PlanStalled(f"closure planning child {why}")
    for reader in readers:
        reader.join()
    stdout = "".join(out)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, stdout, "\n".join(tail))
    return stdout


def distribution_plans(profile: str, jobs, target: str, python_version: str, *,
                       stall: float = PLAN_STALL_SECONDS, cap: float = PLAN_TIMEOUT_SECONDS
                       ) -> list[dict[str, tuple[set[str], list[str]]]]:
    """``jobs``: ``[(sites, {key: extras})]`` -> per job ``{key: (the distributions it ships, refusals)}``.

    The closure script is the one authority for what ships (its declaration-
    aware model: base dependencies, the manifest's extras — plus a selection's
    extras for an engine pack — and omissions). ONE child interpreter answers
    every job: one walk of the profile (each file parsed once), then per job the
    distribution metadata of ITS ``sites`` alone (``-I -S``: the pool's or the
    bundle's own), with the target environment set to ``target``, writing no
    bytecode into them (``-B``).
    """
    payload = [{"sites": [str(site) for site in sites], "selections": {k: list(v) for k, v in selections.items()}}
               for sites, selections in jobs]
    cmd = [sys.executable, "-I", "-S", "-B", "-c", _DISTRIBUTION_DRIVER, str(ROOT), json.dumps(payload), profile,
           json.dumps(marker_env(target, python_version)), str(PROGRESS_INTERVAL_SECONDS)]
    out = json.loads(_run_planner(cmd, stall, cap).strip().splitlines()[-1])
    counts = out["counts"]
    print(f"closure plan: {len(jobs)} site set(s), "
          f"{sum(len(selections) for _, selections in jobs)} selection(s), {counts['walks']} walk(s), "
          f"{counts['parses']} file(s) parsed", flush=True)
    return [{key: (set(plan["needed"]), plan["refusals"]) for key, plan in job.items()} for job in out["jobs"]]


def distribution_plan(profile: str, sites: list[Path], target: str, python_version: str,
                      extra_extras=()) -> tuple[set[str], list[str]]:
    """-> (the distributions the closure ships, its refusals): one selection, see :func:`distribution_plans`."""
    return distribution_plans(profile, [(sites, {CORE: tuple(extra_extras)})], target, python_version)[0][CORE]


def pack_selections(manifest, packs=None) -> dict[str, tuple[str, ...]]:
    """The core's selection plus one per engine pack (``packs``: a subset; default every pack)."""
    names = manifest.packaging_packs if packs is None else packs
    return {CORE: (), **{pack: tuple(manifest.packaging_packs[pack]) for pack in names}}


def pack_from_plans(plans: dict, pack: str) -> tuple[set[str], list[str]]:
    """An engine pack: what its selection ships and the core's does not (``plans``: one job's answer)."""
    core, refused = plans[CORE]
    full, refused_full = plans[pack]
    return full - core, [*refused, *refused_full]


def make_plan(manifest, site: Path, target: str, python_version: str,
              index: dict[str, Path] | None = None,
              distributions: tuple[set[str], list[str]] | None = None) -> Plan:
    """The CORE bundle: the profile's closure with its own extras (no engine pack). ``distributions``:
    the core's answer from a :func:`distribution_plans` run over ``site``, when the caller has one."""
    first_party, loaded, _ = first_party_plan(manifest, index)
    needed, refused = distributions or distribution_plan(manifest.profile, [site], target, python_version)
    return Plan(profile=manifest.profile, target=target, python_version=python_version,
                first_party=first_party, pinned=loaded, distributions=needed,
                missing=needed - set(read_site(site)), refusals=refused,
                sibling=forced_tree_plan(manifest, first_party, loaded))


def pack_distributions(manifest, pack: str, sites: list[Path], target: str,
                       python_version: str) -> tuple[set[str], list[str]]:
    """An engine pack: what the closure ships WITH the pack's extras and the core does not."""
    plans = distribution_plans(manifest.profile, [(sites, pack_selections(manifest, [pack]))], target,
                               python_version)[0]
    return pack_from_plans(plans, pack)
