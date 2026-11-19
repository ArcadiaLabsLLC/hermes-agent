"""PM pins the python-build-standalone flavor pm/_fork_python_flavor.py names, and `pm update` keeps it.

RT-BUNDLED-LINUX-INTERPRETER-STRIPPED-AND-PRUNED: the flavor was hard-coded `install_only`, so a hand
re-pin of the stripped build would be undone by the next `pm update`.
"""

from __future__ import annotations

import json
from pathlib import Path

from pm import cli
from pm._fork_python_flavor import PBS_FLAVOR, pbs_flavor
from pm.registry import get_package
from pm.update import Resolved

ROOT = Path(__file__).resolve().parents[2]


def _name(url: str) -> str:
    return url.rsplit("/", 1)[1]


def test_linux_desktop_targets_download_the_stripped_build_and_the_rest_keep_install_only():
    python = get_package("python")
    for target in ("linux-x64", "linux-arm64"):
        assert _name(python.fetch_url("3.14.9+20261021", target)).endswith("-install_only_stripped.tar.gz"), target
    for target in ("darwin-arm64", "darwin-x64", "win32-x64", "win32-arm64", "linux-x64-musl"):
        assert _name(python.fetch_url("3.14.9+20261021", target)).endswith("-install_only.tar.gz"), target
    assert python.fetch_url("3.14.9+20261021", "linux-arm64-bionic").endswith(".deb")


def test_pm_update_re_pins_a_new_interpreter_in_the_targets_flavor(monkeypatch):
    """The re-pin `pm update` runs (`_pin_artifacts`) builds every URL through the flavor, so it never
    swaps the stripped build back for the debug one."""
    monkeypatch.setattr(cli, "hash_url", lambda url: "0" * 64)
    python = get_package("python")
    current = json.loads((ROOT / "pm" / "lock.json").read_text(encoding="utf-8"))["packages"]["python"]["artifacts"]
    decision = Resolved("python", "3.14.9+20261021", python.version_style, version="3.14.10+20991231",
                        per_target={"linux-x64": "3.14.10+20991231", "darwin-arm64": "3.14.10+20991231"})
    pinned = cli._pin_artifacts(python, decision, current)
    assert _name(pinned["linux-x64"]["url"]) == (
        "cpython-3.14.10+20991231-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz")
    assert _name(pinned["darwin-arm64"]["url"]) == "cpython-3.14.10+20991231-aarch64-apple-darwin-install_only.tar.gz"


def test_pms_own_python_pin_is_written_through_the_flavor():
    """pm/lock.json was re-pinned through fetch_url, not by hand: every python-build-standalone row is the
    URL the flavor builds for its target."""
    python_pin = json.loads((ROOT / "pm" / "lock.json").read_text(encoding="utf-8"))["packages"]["python"]
    python = get_package("python")
    for target, artifact in python_pin["artifacts"].items():
        assert artifact["url"] == python.fetch_url(python_pin["version"], target), target
    assert {pbs_flavor(target) for target in PBS_FLAVOR} == {"install_only_stripped"}
