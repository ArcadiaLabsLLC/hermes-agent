"""Rule 3 fence: the harness plugin never imports the fork's edits to upstream files.

Plan: ``docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md`` §1
rule 3. ``plugins/eternia-harness/`` must stay installable on stock upstream, so every
import it makes — module level or deferred inside a function — resolves to either

* a FORK-ONLY module (its file is not in the upstream manifest), or
* an UPSTREAM module and a PUBLIC name that module already defined at the manifest
  base (``git show <base>:<path>``): no ``_private`` name, and no name the fork added.

The walk enumerates the plugin's own files (``rglob``) and every ``Import`` /
``ImportFrom`` node in each (``ast.walk``), so a lazy import inside a render or setup
callable is fenced exactly like a top-level one.
"""

from __future__ import annotations

import ast
import subprocess
from functools import lru_cache
from pathlib import Path

from scripts.upstream_footprint import MANIFEST, read_manifest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "eternia-harness"


@lru_cache(maxsize=None)
def _manifest() -> tuple[str, frozenset[str]]:
    base, paths = read_manifest(MANIFEST)
    return base, frozenset(paths)


def _module_path(module: str, paths: frozenset[str]) -> str | None:
    """The upstream manifest path a dotted module name resolves to, or None (fork-only)."""
    stem = module.replace(".", "/")
    for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
        if candidate in paths:
            return candidate
    return None


def _is_repo_module(module: str) -> bool:
    stem = ROOT / module.replace(".", "/")
    return stem.with_suffix(".py").is_file() or (stem / "__init__.py").is_file()


@lru_cache(maxsize=None)
def _base_names(path: str) -> frozenset[str]:
    """Top-level names ``path`` defined at the manifest base."""
    base, _ = _manifest()
    source = subprocess.run(
        ["git", "show", f"{base}:{path}"], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return frozenset(names)


def violations(source: str, filename: str = "<plugin>") -> list[str]:
    """Every import in ``source`` that reaches past upstream's public surface."""
    _, paths = _manifest()
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                path = _module_path(alias.name, paths)
                if path is not None and any(part.startswith("_") for part in alias.name.split(".")):
                    found.append(f"{filename}:{node.lineno}: import {alias.name} (private upstream module)")
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            path = _module_path(node.module, paths)
            if path is None:
                continue  # fork-only module: ours to import
            for alias in node.names:
                submodule = f"{node.module}.{alias.name}"
                if _module_path(submodule, paths) is not None:  # an upstream submodule
                    if alias.name.startswith("_"):
                        found.append(f"{filename}:{node.lineno}: {submodule} is a private upstream module")
                    continue
                if _is_repo_module(submodule):
                    continue  # a fork-only submodule of an upstream package: ours to import
                if alias.name.startswith("_"):
                    found.append(f"{filename}:{node.lineno}: {node.module}.{alias.name} is private upstream")
                elif alias.name not in _base_names(path):
                    found.append(f"{filename}:{node.lineno}: {node.module}.{alias.name} is not in "
                                 f"{path} at the manifest base (a fork edit to an upstream file)")
    return found


def test_the_plugin_imports_upstream_only_through_its_public_surface():
    files = sorted(PLUGIN.rglob("*.py"))
    assert files, f"no plugin sources under {PLUGIN}"
    found = [v for f in files for v in violations(f.read_text(encoding="utf-8"), str(f.relative_to(ROOT)))]
    assert not found, "\n".join(found)


def test_the_fence_reds_on_a_fork_added_name_in_an_upstream_file():
    """Positive control: ``record_api_call_usage`` is the fork's addition to the
    upstream ``agent/usage_pricing.py`` — importing it lazily must be caught."""
    planted = "def f():\n    from agent.usage_pricing import record_api_call_usage\n"
    assert violations(planted) == [
        "<plugin>:2: agent.usage_pricing.record_api_call_usage is not in agent/usage_pricing.py "
        "at the manifest base (a fork edit to an upstream file)"
    ]
    # Same module, a name upstream shipped at the base: allowed.
    assert violations("from agent.usage_pricing import CanonicalUsage\n") == []


def test_the_fence_reds_on_a_private_upstream_name_and_passes_fork_modules():
    assert violations("from hermes_cli.plugins import _ensure_plugins_discovered\n") == [
        "<plugin>:1: hermes_cli.plugins._ensure_plugins_discovered is private upstream"
    ]
    assert violations("from agent_runtime.prompt_guidance import TOOL_DESCRIBE_GUIDANCE\n") == []
    assert violations("from hermes_cli.harness import build_cli_parser\n") == []
    assert violations("from hermes_cli import _boot_clock\n") == []  # fork-only submodule
