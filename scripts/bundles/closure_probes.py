"""The closure's child-interpreter probes: what importing the roots loads, and what a stand-in answers.

Split out of ``scripts/bundle_profile_closure.py`` (W0-G1 size ceiling); that module re-exports both.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


_BOOT_PROBE = "; ".join([
    "import importlib, json, sys",
    "[importlib.import_module(m) for m in sys.argv[1:]]",
    "print(json.dumps(sorted({n.split('.')[0] for n in sys.modules})))",
])


def boot_tops(roots, first_party_tops) -> set[str]:
    """Instrumented lower bound: third-party tops actually loaded by importing ``roots``."""
    import subprocess

    done = subprocess.run([sys.executable, "-c", _BOOT_PROBE, *roots], cwd=ROOT, capture_output=True,
                          text=True, timeout=300, check=True)
    loaded = json.loads(done.stdout.strip().splitlines()[-1])
    return {t for t in loaded if t not in first_party_tops and t not in sys.stdlib_module_names
            and not t.startswith("_")}


#: Asked in a child interpreter with the omitted imports made unfindable: the stand-in module's
#: ``stand_in_modules()`` is registered in ``sys.modules`` and each dotted name is resolved on the
#: module that is actually there (the longest registered prefix, then attributes).
_STAND_IN_PROBE = r"""
import importlib, json, sys
root, blocked, stand_in, wanted = sys.argv[1], set(json.loads(sys.argv[2])), sys.argv[3], json.loads(sys.argv[4])
sys.path.insert(0, root)

class Absent:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in blocked:
            raise ModuleNotFoundError(f"omitted: {name}", name=name)

sys.meta_path.insert(0, Absent())
sys.modules.update(importlib.import_module(stand_in).stand_in_modules())

def answers(dotted):
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        head = sys.modules.get(".".join(parts[:i]))
        if head is None:
            continue
        try:
            for name in parts[i:]:
                head = getattr(head, name)
        except AttributeError:
            return False
        return True
    return False

print(json.dumps(sorted(d for d in wanted if answers(d))))
"""


def stand_in_answered(manifest, unguarded: dict[str, list[dict]]) -> dict[str, list[str]]:
    """distribution -> the unguarded dotted names its row's ``stand_in`` answers at run time.

    An omitted distribution may name a first-party ``stand_in`` module (the phone's ``openai``,
    ``agent_runtime.provider_sdk_shim``) whose ``stand_in_modules()`` the profile's entry registers
    before any import site runs. A site it answers is a seam proven in a child interpreter, never by
    reading the stand-in's spelling: a name it lacks does not resolve there and stays refused."""
    import subprocess

    out: dict[str, list[str]] = {}
    for row in manifest.omitted_distributions:
        stand_in, sites = row.get("stand_in"), unguarded.get(row["distribution"]) or []
        wanted = sorted({site["dotted"] for site in sites if site.get("dotted")})
        if not stand_in or not wanted:
            continue
        done = subprocess.run(
            [sys.executable, "-c", _STAND_IN_PROBE, str(ROOT), json.dumps(list(row["imports"])), stand_in,
             json.dumps(wanted)], capture_output=True, text=True, timeout=300, cwd=ROOT, check=False)
        if done.returncode != 0:
            raise RuntimeError(f"stand-in probe failed for {stand_in}: {done.stderr[-2000:]}")
        out[row["distribution"]] = json.loads(done.stdout.strip().splitlines()[-1])
    return out
