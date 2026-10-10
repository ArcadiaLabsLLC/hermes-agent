"""The census of plugin toolsets no persona declares (tool-visibility split, slice 2).

Plan: ``docs/agent-runtime-harness/planned/tool-visibility-authority-split-2026-10-08.md`` §3
slice 2. The case it exists for: a teammate's Lens plugin registered tools into a toolset
no profile declared, reached no persona, and nothing said so. Each case registers a REAL
tool into toolset ``eternia_lens`` on the live ``tools.registry.registry`` (a fake plugin,
not a fixture of names) and removes it afterwards.
"""

from __future__ import annotations

import logging

import pytest

from agent_runtime.personas import TOOLSET_SOURCE_PROFILE_CONFIG, ToolsetDeclaration
from agent_runtime.toolset_census import (
    log_serve_toolset_census,
    toolset_census,
    undeclared_registered_toolsets,
)
from agent_runtime.toolset_names import expand_toolset_names

LENS = "eternia_lens"
LENS_TOOL = "eternia_lens_capture_probe"


def _declaration(*names: str) -> ToolsetDeclaration:
    return ToolsetDeclaration(
        toolsets=tuple(expand_toolset_names(names)),
        declared=tuple(names),
        source=TOOLSET_SOURCE_PROFILE_CONFIG,
    )


@pytest.fixture
def lens_plugin():
    """Register one tool into ``eternia_lens`` the way a plugin's ``register(ctx)`` does."""

    from hermes_cli.plugins import discover_plugins
    from tools.registry import registry

    discover_plugins()  # the census's own first step, paid before the baseline is read
    registry.register(
        name=LENS_TOOL,
        toolset=LENS,
        schema={
            "name": LENS_TOOL,
            "description": "test-only lens probe",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=lambda args, **kwargs: "{}",
    )
    try:
        yield
    finally:
        registry.deregister(LENS_TOOL)


def test_a_plugin_toolset_no_profile_declares_is_named():
    before = toolset_census([_declaration("harness_core")])
    assert LENS not in before.registered

    from tools.registry import registry

    registry.register(
        name=LENS_TOOL,
        toolset=LENS,
        schema={"name": LENS_TOOL, "description": "probe", "parameters": {"type": "object", "properties": {}}},
        handler=lambda args, **kwargs: "{}",
    )
    try:
        after = undeclared_registered_toolsets([_declaration("harness_core")])
        declared_too = undeclared_registered_toolsets([_declaration("harness_core", LENS)])
    finally:
        registry.deregister(LENS_TOOL)

    # Exactly the fake joined the answer — nothing the baseline did not already say.
    assert after == tuple(sorted(set(before.undeclared) | {LENS}))
    # Positive control: declaring it clears it, and only it.
    assert declared_too == before.undeclared


def test_builtin_and_mcp_toolsets_are_never_census_rows(lens_plugin):
    census = toolset_census([_declaration("harness_core")])

    from tools.toolset_manifest import builtin_toolset_names

    assert not set(census.registered) & set(builtin_toolset_names())
    assert not [name for name in census.registered if name.startswith("mcp-")]
    assert LENS in census.registered


def test_the_serve_boot_logs_one_census_line(lens_plugin, isolate_agent_runtime_root, caplog):
    caplog.set_level(logging.INFO, logger="agent_runtime.toolset_census")

    census = log_serve_toolset_census()

    records = [r for r in caplog.records if r.getMessage().startswith("toolset_census ")]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert LENS in records[0].getMessage()
    assert census is not None and LENS in census.undeclared
    assert f"registered={len(census.registered)}" in records[0].getMessage()


def test_the_serve_entry_point_wires_the_real_census(monkeypatch):
    """The loop's ``toolset_census`` defaults OFF, so the production wiring in
    ``serve/commands.py`` is what makes the boot receipt real — pin it, or the
    census ships dead with every loop test green.

    *Killing mutation:* drop ``toolset_census=log_serve_toolset_census`` from
    ``_cmd_serve``'s ``serve_loop`` call."""

    import os
    from types import SimpleNamespace

    from hermes_cli.harness_parts.serve import commands as serve_mod

    captured: dict = {}
    monkeypatch.setattr(
        serve_mod,
        "_claim_protocol_pipes",
        lambda: (os.open(os.devnull, os.O_RDONLY), os.open(os.devnull, os.O_WRONLY)),
    )
    monkeypatch.setattr(serve_mod, "serve_loop", lambda reader, writer, **kw: captured.update(kw) or 0)

    assert serve_mod._cmd_serve(SimpleNamespace(ndjson=True, pool_size=1, no_socket=True)) == 0
    assert captured.get("toolset_census") is log_serve_toolset_census


def test_the_census_runs_fourth_and_last_on_the_one_prewarm_thread():
    """After the provider warmup has discovered the plugins, so the census reads a
    populated registry. Positive control: the census alone still gets a thread.

    *Killing mutation:* move ``toolset_census`` ahead of ``self.actor_prewarm``
    in the prewarm worker's step tuple."""

    import io
    import threading

    from hermes_cli.harness_parts.serve import serve_loop

    order: list[str] = []
    done = threading.Event()
    serve_loop(
        iter(['{"id":"1","op":"shutdown"}']),
        io.StringIO(),
        dispatch=lambda argv: 0,
        snapshot_prewarm=lambda: order.append("snapshot"),
        provider_prewarm=lambda: order.append("provider"),
        actor_prewarm=lambda: order.append("actor"),
        toolset_census=lambda: (order.append("census"), done.set()),
    )
    assert done.wait(10)
    assert order == ["snapshot", "provider", "actor", "census"]

    alone = threading.Event()
    serve_loop(
        iter(['{"id":"1","op":"shutdown"}']),
        io.StringIO(),
        dispatch=lambda argv: 0,
        toolset_census=alone.set,
    )
    assert alone.wait(10)
