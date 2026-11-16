"""FH-RUNTIME-HOME-DEFAULT-DUPLICATE: the agent-runtime default home is hermes_constants' default.

``agent_runtime.host_tools.platform_default_root`` (the root ``agent_runtime.resolution`` resolves
with) reads a passed environment mapping, so it restates
``hermes_constants._get_platform_default_hermes_home`` (which reads ``os.environ``); this pins the
two to one answer, ``HERMES_DATA_DIR_SUFFIX`` included.
"""

import os

import pytest

import hermes_constants
from agent_runtime import host_tools


@pytest.mark.parametrize("suffix", ["", "-dev"])
def test_the_runtime_default_home_is_the_constants_default(monkeypatch, tmp_path, suffix):
    # Off the native parent, so the suite's isolation of the constants default answers the real rule.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    if suffix:
        monkeypatch.setenv("HERMES_DATA_DIR_SUFFIX", suffix)
    else:
        monkeypatch.delenv("HERMES_DATA_DIR_SUFFIX", raising=False)
    assert host_tools.platform_default_root(os.environ) == hermes_constants._get_platform_default_hermes_home()


def test_the_suffix_is_read_from_the_mapping_not_the_process(monkeypatch):
    monkeypatch.delenv("HERMES_DATA_DIR_SUFFIX", raising=False)
    env = {**os.environ, "HERMES_DATA_DIR_SUFFIX": "-dev"}
    assert host_tools.platform_default_root(env).name in {"hermes-dev", ".hermes-dev"}
