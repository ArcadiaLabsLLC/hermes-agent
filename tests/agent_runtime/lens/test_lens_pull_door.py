"""Lens L4 — the pull door (plan ``p10-agent-2026-10-19.md`` §5.5).

A persona whose profile declares the ``lens`` toolset reads a monitor's recorded
numbers (``lens_read``) and proposes a monitor as a DRAFT the operator seals
(``lens_propose``); L4.3 adds the ``sql_readonly`` and ``command_allowlisted``
sources and Prometheus through ``kubectl proxy``.

No serve is started and no model is called: the tools are driven as functions,
the plugin's real ``register`` runs against a recording context, and the home is
the test's isolated ``HERMES_HOME``.

Gates and their killing mutations (each red was recorded in the stage's commit):

* L4.1 ``lens_read``: a profile that does not declare ``lens`` reaches the tool —
  killed by registering ``lens_read`` into ``agent_chat`` (a ``harness_core``
  member) instead of ``lens``; a range read answers more than its bound — killed
  by dropping ``limit=TOOL_SERIES_ROWS`` from ``read_lens`` (300 rows answered).
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, UTC
from pathlib import Path

import pytest

from agent_runtime.lens.store import LensStore, MonitorState, to_ms

T0 = datetime(2026, 10, 19, 12, tzinfo=UTC)
PLUGIN = Path(__file__).resolve().parents[3] / "plugins" / "eternia-lens" / "__init__.py"


def _manifest(monitor_id: str = "status", feeds: list[dict] | None = None) -> dict:
    feed = {"version": 1, "id": "latency", "kind": "http_json", "interval_ms": 60_000,
            "source": {"url": "https://status.example.invalid/api", "selector": "$.latency"}}
    return {"version": 1, "monitor_id": monitor_id, "feeds": feeds or [feed], "rules": [],
            "automation": {"level": "notify", "when": "always", "daily_turn_cap": 4}, "persona_id": None}


def _sealed(manifest: dict | None = None) -> LensStore:
    manifest = manifest or _manifest()
    store = LensStore()
    store.create(manifest)
    store.seal(manifest["monitor_id"])
    store.set_state(manifest["monitor_id"], MonitorState.ENABLED)
    return store


def _plugin_tools() -> dict[str, str]:
    """The plugin's real ``register`` against a recording context: tool name -> toolset."""

    spec = importlib.util.spec_from_file_location("_eternia_lens_pull_door_under_test", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tools: dict[str, str] = {}

    class RecordingCtx:
        def register_tool(self, name, toolset, **_kwargs):
            tools[name] = toolset

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    module.register(RecordingCtx())
    return tools


# --- L4.1 lens_read ---------------------------------------------------------------


def test_a_profile_that_does_not_declare_lens_never_reaches_lens_read(bundled_persona_profiles):
    import textwrap

    import model_tools
    from agent_runtime.harness_toolset import HARNESS_CORE_INCLUDES
    from agent_runtime.lens.tool import LENS_TOOLSET
    from agent_runtime.models import AgentPersona
    from agent_runtime.parse_cache import clear_parse_cache
    from agent_runtime.persona_profiles import effective_toolsets
    from hermes_cli.profiles import get_profile_dir

    def admitted(declared: str) -> set[str]:
        home = get_profile_dir("lens-probe")
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text(textwrap.dedent(declared), encoding="utf-8")
        clear_parse_cache()
        persona = AgentPersona(id="lens-probe", display_name="Lens probe", role="dev", model=None, provider=None,
                               api_mode="codex_responses", system_prompt_path="", hermes_profile="lens-probe")
        definitions = model_tools.get_tool_definitions(enabled_toolsets=effective_toolsets(persona),
                                                       quiet_mode=True, skip_tool_search_assembly=True)
        return {definition["function"]["name"] for definition in definitions}

    undeclared = admitted("toolsets:\n  - harness_core\n")
    declared = admitted("toolsets:\n  - harness_core\n  - lens\n")
    assert "lens_read" in declared, "positive control: a profile that declares lens reaches the tool"
    assert "lens_read" not in undeclared
    assert "terminal" in undeclared, "positive control: the undeclared profile resolved harness_core"
    tools = _plugin_tools()
    assert tools.get("lens_read") == LENS_TOOLSET == "lens"
    assert LENS_TOOLSET not in HARNESS_CORE_INCLUDES


def test_lens_read_answers_latest_and_a_bounded_range_with_explicit_gaps():
    from agent_runtime.lens.tool import TOOL_SERIES_ROWS, handle_lens_read, read_lens

    store = _sealed()
    for minute in range(300):
        at = T0 - timedelta(minutes=300 - minute)
        value = None if minute % 50 == 0 else float(minute)
        store.record("status", "latency", observed_at=at, received_at=at, value=value,
                     reason="ok" if value is not None else "timeout")

    latest = read_lens({"monitor": "status"}, store=store, now=T0)
    assert [row["value"] for row in latest["latest"]] == [299.0]

    series = read_lens({"monitor": "status", "feed": "latency", "range": {"minutes": 360}}, store=store, now=T0)
    assert series["series"] == "lens-range-v1" and series["truncated"] is True
    assert len(series["observations"]) == TOOL_SERIES_ROWS
    gaps = [row for row in series["observations"] if row["gap"]]
    assert gaps and all(row["value"] is None and row["reason"] == "timeout" for row in gaps)

    explicit = read_lens({"monitor": "status", "feed": "latency",
                          "range": {"start_ms": to_ms(T0 - timedelta(minutes=10)), "end_ms": to_ms(T0)}},
                         store=store, now=T0)
    assert [row["value"] for row in explicit["observations"]] == [float(m) for m in range(290, 300)]
    assert explicit["truncated"] is False

    assert json.loads(handle_lens_read({"monitor": "status", "range": {"minutes": 5}})) == {
        "error": "invalid_value", "detail": "range needs a feed"}
    assert json.loads(handle_lens_read({"monitor": "nobody"})) == {"error": "monitor_not_found"}
    assert json.loads(handle_lens_read({"monitor": "status", "feed": "latency", "range": {"minutes": 99_999}}))[
        "error"] == "invalid_integer"
