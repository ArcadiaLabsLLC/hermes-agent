"""The system-temp sweep removes this repo's aged leftovers by name, and only those (D3.08).

Exercised over a fake system temp dir: an aged known-prefix entry goes and is
named; a fresh one, a foreign-prefix one (a launcher sandbox) and an aged
foreign one stay.
"""

from __future__ import annotations

import os
import shutil
import time

from tests._downstream.temp_prefixes import HERMES_TEMP_PREFIXES, sweep_system_temp, system_temp_dirs


def _aged(path, days=2):
    stamp = time.time() - days * 24 * 3600
    os.utime(path, (stamp, stamp))
    return path


def test_an_aged_known_prefix_entry_is_removed_and_named_and_the_rest_kept(tmp_path):
    temp = tmp_path / "Temp"
    temp.mkdir()
    aged_home = temp / "hermes-test-home-abc123"
    (aged_home / "profiles").mkdir(parents=True)
    _aged(aged_home)
    aged_scratch = temp / "hermes-pytest"
    aged_scratch.mkdir()
    _aged(aged_scratch)
    fresh_home = temp / "hermes-test-home-fresh"
    fresh_home.mkdir()
    foreign_aged = temp / "realm_sync_test_cred42"
    foreign_aged.mkdir()
    _aged(foreign_aged)

    removed = sweep_system_temp([str(temp)], now=time.time(), rmtree=shutil.rmtree)

    assert sorted(removed) == sorted([str(aged_home), str(aged_scratch)])
    assert not aged_home.exists() and not aged_scratch.exists()
    assert fresh_home.exists() and foreign_aged.exists()


def test_no_launcher_prefix_is_on_the_list():
    assert all(prefix.startswith("hermes-") for prefix in HERMES_TEMP_PREFIXES)


def test_the_redirect_root_is_never_a_system_temp_dir(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    system = tmp_path / "system"
    system.mkdir()
    env = {"TEMP": str(root), "TMP": str(root / "run-1"), "TMPDIR": str(system), "LOCALAPPDATA": str(tmp_path / "none")}
    (root / "run-1").mkdir()

    assert system_temp_dirs(env, str(root)) == [os.path.realpath(system)]


def test_the_plugin_names_each_removed_entry_in_the_root_log(tmp_path):
    from tests._downstream.conftest_plugin import _sweep_system_temp_named

    root = tmp_path / "root"
    root.mkdir()
    temp = tmp_path / "Temp"
    leftover = temp / "hermes-stream-fixtures-x1"
    leftover.mkdir(parents=True)
    _aged(leftover)

    removed = _sweep_system_temp_named({"TEMP": str(temp)}, str(root), time.time())

    assert [os.path.realpath(path) for path in removed] == [os.path.realpath(leftover)]
    assert not leftover.exists()
    assert f"removed {removed[0]}" in (root / ".temp-sweep.log").read_text(encoding="utf-8")
