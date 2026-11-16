"""A hermes child the session spawns skips the bundled-manifest parse and the git version lookup.

Pins ``tests/_downstream/child_startup.py`` + ``tests/_downstream/child_site/sitecustomize.py``
(row: every hermes child repeats provider discovery and the git version lookup).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests._downstream import child_startup

REPO = Path(__file__).resolve().parents[1]

_CHILD = r"""
import json, subprocess, sys
spawned = []
_real = subprocess.Popen.__init__
def _count(self, args, *a, **k):
    argv = args if isinstance(args, str) else " ".join(map(str, args))
    if "git" in argv.split(" ", 1)[0].lower():
        spawned.append(argv)
    _real(self, args, *a, **k)
subprocess.Popen.__init__ = _count
import hermes_cli.config as config
import hermes_cli.banner as banner
from hermes_cli.version_info import get_code_identity, get_version_info
banner.prefetch_update_check()
banner.prefetch_banner_data()
first = get_version_info()
identity = get_code_identity(refresh=True)
stats = getattr(sys.modules.get("sitecustomize"), "stats", None)
print(json.dumps({"git": spawned, "stats": stats, "identity": identity,
                  "display": first.display_version, "env_vars": sorted(config.OPTIONAL_ENV_VARS)}))
"""


def _child(snapshot: Path, *, shortcut: bool = True) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in {child_startup.ENV, "PYTHONPATH"}}
    env["PYTHONPATH"] = str(REPO)
    if shortcut:
        child_startup.install(env, snapshot)
    done = subprocess.run([sys.executable, "-c", _CHILD], cwd=REPO, env=env, capture_output=True,
                          text=True, timeout=180, check=False)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_spawned_child_skips_the_manifest_parse_and_the_git_version_lookup(tmp_path):
    snapshot = tmp_path / "snapshot"
    cold = _child(snapshot)
    # The cold child took the production path and recorded what it found.
    assert cold["stats"]["version_miss"] >= 1 and cold["stats"]["manifest_miss"] >= 20, cold["stats"]
    assert any("status" in argv for argv in cold["git"]), cold["git"]

    warm = _child(snapshot)
    assert warm["git"] == [], warm["git"]
    assert warm["stats"]["manifest_miss"] == 0, warm["stats"]
    assert warm["stats"]["manifest_hit"] >= 20 and warm["stats"]["version_hit"] >= 2, warm["stats"]
    assert warm["stats"]["prefetch_off"] >= 2, warm["stats"]

    # Same answers as a child with no shortcut at all.
    plain = _child(snapshot, shortcut=False)
    for key in ("identity", "display", "env_vars"):
        assert warm[key] == plain[key] == cold[key], key


def test_an_edited_manifest_is_parsed_again(tmp_path):
    snapshot = tmp_path / "snapshot"
    _child(snapshot)
    recorded = json.loads((snapshot / "manifests.json").read_text(encoding="utf-8"))
    path = next(iter(recorded))
    recorded[path]["sig"][1] += 1  # the file's size no longer matches
    (snapshot / "manifests.json").write_text(json.dumps(recorded), encoding="utf-8")
    assert _child(snapshot)["stats"]["manifest_miss"] == 1


def test_another_commit_resolves_git_again(tmp_path):
    snapshot = tmp_path / "snapshot"
    _child(snapshot)
    recorded = json.loads((snapshot / "version.json").read_text(encoding="utf-8"))
    recorded["head"] = "0" * 40
    (snapshot / "version.json").write_text(json.dumps(recorded), encoding="utf-8")
    again = _child(snapshot)
    assert again["stats"]["version_miss"] == 1 and any("status" in a for a in again["git"]), again


_BOTH_FINDERS = r"""
import json, sys
from agent_runtime.spawn_stand_ins import StandIn, install_spawn_stand_ins, is_spawn_stand_in
assert "hermes_cli.version_info" not in sys.modules
install_spawn_stand_ins((StandIn("hermes_cli.version_info", "_run_git", returns=None),))
import hermes_cli.version_info as module
print(json.dumps({"rebound": is_spawn_stand_in(vars(module)["_run_git"]),
                  "hooked": hasattr(module._git_version_info, "__wrapped__")}))
"""


def test_a_module_both_finders_hook_imports_once_with_both_applied(tmp_path):
    """FH-CHILD-STARTUP-FINDER-AND-SPAWN-STAND-INS-RECURSE: the start-up finder and the spawn
    stand-ins' rebinding finder each delegate to every other finder; without ``_AfterImport``'s
    re-entry guard a name both hook recursed until RecursionError."""
    env = {k: v for k, v in os.environ.items() if k not in {child_startup.ENV, "PYTHONPATH"}}
    env["PYTHONPATH"] = str(REPO)
    child_startup.install(env, tmp_path / "snapshot")
    done = subprocess.run([sys.executable, "-c", _BOTH_FINDERS], cwd=REPO, env=env, capture_output=True,
                          text=True, timeout=180, check=False)
    assert done.returncode == 0, done.stderr[-3000:]
    assert json.loads(done.stdout.strip().splitlines()[-1]) == {"rebound": True, "hooked": True}
