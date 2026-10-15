"""No fork-owned module imports ``yaml`` (pyyaml) — YAML goes through ``agent_runtime.yaml_io``.

Upstream's core dependencies carry only ``ruamel.yaml`` on Python 3.14, so the
pm-committed environment ``hermes update`` builds has no ``pyyaml``, and a fork
module that imports it is unimportable there (the harness CLI plugin fails to
attach; Mission Control reports "installation needs repair"). The fix is to
adopt upstream's dependency, never to pin pyyaml in ``pyproject.toml``.

This is a "must never be written" rule, so a source walk is the right shape:
it over-approximates (an import under ``if TYPE_CHECKING`` or ``try`` still
counts), which is the safe direction. Population: every tracked ``.py`` not in
the upstream manifest (``scripts/god_file_probe.upstream_paths``), tests
included — a fork test that imports pyyaml fails to collect in the same env.
"""

from __future__ import annotations

import ast
import subprocess

from scripts import god_file_probe as probe

_FORBIDDEN = "yaml"


def _names_pyyaml(module: str | None) -> bool:
    return module is not None and (
        module == _FORBIDDEN or module.startswith(_FORBIDDEN + ".")
    )


def pyyaml_imports(source: str, path: str = "<string>") -> list[int]:
    """Line numbers where ``source`` imports pyyaml (``import``, ``from``, or a literal dynamic import)."""
    found: list[int] = []
    for node in ast.walk(ast.parse(source, filename=path)):
        if isinstance(node, ast.Import) and any(
            _names_pyyaml(alias.name) for alias in node.names
        ):
            found.append(node.lineno)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and _names_pyyaml(node.module)
        ):
            found.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", None)
            )
            if name in {"__import__", "import_module"} and _names_pyyaml(
                str(node.args[0].value)
            ):
                found.append(node.lineno)
    return found


def _fork_python_files() -> list[str]:
    root = probe.ROOT
    tracked = (
        subprocess
        .run(
            ["git", "ls-files", "-z", "--", "*.py"],
            cwd=root,
            capture_output=True,
            check=True,
        )
        .stdout.decode("utf-8")
        .split("\0")
    )
    upstream = probe.upstream_paths()
    return sorted(
        p for p in tracked if p and p not in upstream and (root / p).is_file()
    )


def test_no_fork_owned_module_imports_pyyaml():
    root = probe.ROOT
    population = _fork_python_files()
    assert len(population) > 1000, (
        f"the fork population came back implausibly small: {len(population)}"
    )
    offenders = [
        f"{path}:{line}"
        for path in population
        for line in pyyaml_imports((root / path).read_text(encoding="utf-8"), path)
    ]
    assert offenders == [], (
        "use `from agent_runtime import yaml_io` instead of pyyaml:\n"
        + "\n".join(offenders)
    )


def test_the_walk_sees_every_spelling_it_forbids():
    """Positive control: each forbidden spelling is flagged; the facade and ruamel are not."""
    for spelling in (
        "import yaml",
        "import yaml as y",
        "import os, yaml.constructor",
        "from yaml import safe_load",
        "from yaml.error import YAMLError",
        "def f():\n    import yaml",
        "importlib.import_module('yaml')",
        "__import__('yaml')",
    ):
        assert pyyaml_imports(spelling), spelling
    for allowed in (
        "from agent_runtime import yaml_io",
        "import ruamel.yaml",
        "from ruamel.yaml import YAML",
        "import hermes_yaml",
        "import yamlish",
        "from . import yaml",
    ):
        assert not pyyaml_imports(allowed), allowed
