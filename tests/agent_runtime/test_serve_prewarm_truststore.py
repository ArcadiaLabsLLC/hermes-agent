"""The serve provider prewarm asks upstream's one TLS authority, failure-isolated.

Upstream deleted ``agent/ssl_guard.py`` (the certifi CA-bundle preflight) for
``agent.ssl_verify.install_truststore()`` at the 2026-09-25 merge; the prewarm
step that called ``verify_ca_bundle()`` was re-seated onto it (design note
``docs/agent-runtime-harness/planned/upstream-merge-2026-09-25-design.md`` §2.1).
These pin the relationship — prewarm -> the one authority, exactly once, and a
raising authority never escapes the prewarm thread — not the function body.
"""

from __future__ import annotations

import agent.ssl_verify as ssl_verify
import model_tools
from hermes_cli.harness_parts import _upstream_doors
from hermes_cli.harness_parts.serve import boot as serve_boot


def _quiet_other_steps(monkeypatch) -> None:
    monkeypatch.setattr(_upstream_doors, "load_openai_cls", lambda: None)
    monkeypatch.setattr(model_tools, "get_tool_definitions", lambda **_kw: [])


def test_prewarm_installs_the_platform_trust_store_once(monkeypatch):
    _quiet_other_steps(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(ssl_verify, "install_truststore", lambda: calls.append("install") or True)

    serve_boot._prewarm_provider_runtime()

    assert calls == ["install"]


def test_prewarm_survives_a_raising_trust_authority(monkeypatch):
    _quiet_other_steps(monkeypatch)
    reached: list[str] = []

    def boom() -> bool:
        raise RuntimeError("truststore exploded")

    monkeypatch.setattr(ssl_verify, "install_truststore", boom)
    monkeypatch.setattr(
        model_tools, "get_tool_definitions", lambda **_kw: reached.append("tools") or []
    )

    serve_boot._prewarm_provider_runtime()

    # The step after the trust store still ran: the failure stayed in its own step.
    assert reached == ["tools"]
