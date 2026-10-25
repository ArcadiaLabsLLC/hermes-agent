"""RT-WORKER-BOOT-PYDANTIC-CONTRACTS: a desktop conversation worker boots on the generated catalog.

Owner 2026-10-22: workers validate with the generated catalog (the phone's shape validator);
pydantic stays in the suite. ``worker_entry.main`` calls ``use_catalog_in_this_process()`` first,
and ``agent_runtime.gateway_extensions`` then leaves the connector RPC modules (the serve forwards a
worker none, and ``methods_connectors_account`` imports pydantic's whole contract package at module
level) unloaded. Measured in a fresh interpreter, because ``sys.modules`` is the guarantee; the
control is the same boot without the call, which must load pydantic.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOOT = """
import sys
sys.path.insert(0, {root!r})
if {catalog!r}:
    from agent_runtime.gateway.contract_seam import use_catalog_in_this_process
    use_catalog_in_this_process()
import tui_gateway.server, tui_gateway.entry
from agent_runtime.conversations import worker_skills, worker_app_functions, process_evidence
worker_skills.install()
worker_app_functions.install()
from agent_runtime.gateway.contract_seam import contract_registry
lines = [str(sorted(m for m in ("pydantic", "tui_gateway.contracts", "tui_gateway.methods_connectors_account")
                   if m in sys.modules)), contract_registry().__name__,
         type(tui_gateway.server._methods_connectors_account).__name__]
open({report!r}, "w", encoding="utf-8").write(chr(10).join(lines))  # the gateway owns stdout
"""


def _boot(tmp_path, catalog: bool) -> list[str]:
    env = {**os.environ, "HERMES_HOME": str(tmp_path / "home"), "PYTHONIOENCODING": "utf-8"}
    report = tmp_path / f"boot-{catalog}.txt"
    out = subprocess.run([sys.executable, "-c", BOOT.format(root=str(ROOT), catalog=catalog, report=str(report))],
                         cwd=ROOT, env=env, check=False, capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    return report.read_text(encoding="utf-8").splitlines()


@pytest.mark.timeout(400)
def test_a_catalog_worker_boots_without_pydantic(tmp_path):
    loaded, registry, connector_methods = _boot(tmp_path, catalog=True)
    assert loaded == "[]"
    assert registry == "agent_runtime.gateway.contract_catalog"
    assert connector_methods == "SimpleNamespace"  # the worker registers no connectors.* method
    # Control: the same boot without the call is the desktop serve's — pydantic and the connector RPCs load.
    loaded, registry, connector_methods = _boot(tmp_path, catalog=False)
    assert "'pydantic'" in loaded and "'tui_gateway.methods_connectors_account'" in loaded
    assert registry == "tui_gateway.contracts.registry"
    assert connector_methods == "module"


def test_worker_entry_forces_the_catalog_before_any_gateway_import():
    source = (ROOT / "agent_runtime" / "conversations" / "worker_entry.py").read_text(encoding="utf-8")
    body = source[source.index("def main() -> None:"):]
    assert body.index("use_catalog_in_this_process()") < body.index("tui_gateway")
