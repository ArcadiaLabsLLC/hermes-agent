"""The C YAML parser is a declared dependency where a wheel exists (owner ruling 2026-10-18, row
RT-TEST-VENV-PURE-YAML): Windows x64 CPython 3.14. Without it every YAML load in tests and in the
hermes children they spawn ran ruamel's pure-Python parser (57 manifest loads 270-290 ms vs 92-130 ms).

Killing mutation: delete the ``ruamel.yaml.clib`` line from ``pyproject.toml`` →
``test_pyproject_declares_the_clib_for_windows_x64_cpython_314`` red.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parents[2]
WIN_X64_314 = {"sys_platform": "win32", "platform_machine": "AMD64", "platform_python_implementation": "CPython",
               "python_version": "3.14", "python_full_version": "3.14.0"}


def _clib() -> list[Requirement]:
    deps = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    return [req for req in map(Requirement, deps) if req.name == "ruamel.yaml.clib"]


def test_pyproject_declares_the_clib_for_windows_x64_cpython_314():
    (req,) = _clib()
    assert req.marker is not None and req.marker.evaluate(WIN_X64_314)
    for other in ({"platform_machine": "ARM64"}, {"python_version": "3.13", "python_full_version": "3.13.5"},
                  {"sys_platform": "linux"}, {"platform_python_implementation": "PyPy"}):
        assert not req.marker.evaluate({**WIN_X64_314, **other}), other


def test_the_interpreter_the_marker_names_loads_the_c_parser():
    (req,) = _clib()
    if not req.marker.evaluate():
        pytest.skip("this interpreter is not one the marker names")
    from ruamel.yaml import YAML
    from ruamel.yaml.cyaml import CParser

    assert YAML(typ="safe").Parser is CParser
