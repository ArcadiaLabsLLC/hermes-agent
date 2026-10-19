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
* L4.2 ``lens_propose``: a proposal seals (or polls) — killed by calling
  ``store.seal`` in ``propose_monitor``; a proposal writes over an existing monitor
  — killed by dropping the ``monitor_exists`` check; a proposal's preview reads a
  private address it did not opt into — killed by passing ``allow_private=True``
  in ``http_json.read`` (the request is made).
* L4.3 sources: a ``DELETE`` reaches ``sql_readonly`` — killed by dropping the
  ``READ_ONLY_STATEMENT`` check in ``sql_readonly.read`` (``query_failed`` from
  SQLite, not ``statement_refused``), or in ``feed.read_only_statement`` (the
  manifest reads); a ``WITH … DELETE`` writes — killed only by dropping BOTH the
  ``mode=ro`` open and ``PRAGMA query_only`` (either alone holds); a command
  outside the allow list runs — killed by dropping the ``allowed`` check in
  ``command.read`` (the marker file is written) or the ``argv in allow`` require in
  ``feed._command_source``; a command runs through a shell — killed by
  ``shell=True`` (cmd runs the ``&`` tail and writes the marker; on POSIX the argv
  tail is dropped and no 7 is read); a preview runs a command — killed by
  dropping the ``SEALED_ONLY_FEED_KINDS`` check; a ``via: kube_proxy`` read is
  refused as private — killed by dropping ``proxied or`` in ``prometheus.read``.
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
    assert {"lens_read", "lens_propose"} <= declared, "positive control: a profile that declares lens reaches them"
    assert not {"lens_read", "lens_propose"} & undeclared
    assert "terminal" in undeclared, "positive control: the undeclared profile resolved harness_core"
    tools = _plugin_tools()
    assert tools == {"lens_read": "lens", "lens_propose": "lens"} and LENS_TOOLSET == "lens"
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


# --- L4.2 lens_propose ------------------------------------------------------------

PUBLIC = ["93.184.216.34"]


def _client(handler):
    import httpx

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _proposal(**feed_overrides) -> dict:
    feed = {"id": "latency", "kind": "http_json", "interval_ms": 60_000,
            "source": {"url": "https://status.example.invalid/api", "selector": "$.latency"}, **feed_overrides}
    return {"monitor_id": "proposed-status", "feeds": [feed],
            "rule": {"id": "slow", "feed_id": "latency", "form": "threshold", "severity": "attention",
                     "direction": "above", "threshold": 500, "recovery_threshold": 400, "window_ms": 0, "samples": 1},
            "automation": {"level": "notify", "when": "always", "daily_turn_cap": 4}}


def test_lens_propose_previews_for_real_and_stores_a_draft_it_never_seals():
    import httpx

    from agent_runtime.lens.poller import LensPoller
    from agent_runtime.lens.tool import handle_lens_propose, propose_monitor

    store, requests = LensStore(), []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, json={"latency": 42})

    answer = propose_monitor(_proposal(), store=store, client=_client(handler), resolver=lambda host: PUBLIC)
    assert answer["preview"] == [{"feed_id": "latency", "status": "available", "number": 42.0, "reason": "ok",
                                  "http_status": 200}]
    assert requests == ["https://status.example.invalid/api"]
    monitor = store.get("proposed-status")
    assert (monitor["state"], monitor["sealed"], answer["sealed"]) == ("draft", None, False)
    assert monitor["draft"]["rules"][0]["id"] == "slow" and monitor["draft"]["version"] == 1
    assert LensPoller(store_factory=lambda: store, client=_client(handler), resolver=lambda host: PUBLIC).tick() == 0
    assert len(requests) == 1, "nothing polls a proposal"

    store.seal("proposed-status")
    again = json.loads(handle_lens_propose(_proposal()))
    assert again == {"error": "monitor_exists"}
    assert store.get("proposed-status")["draft"] is None, "a proposal never writes over a monitor"


def test_lens_propose_previews_through_the_private_address_classifier():
    import httpx

    from agent_runtime.lens.tool import propose_monitor

    store, requests = LensStore(), []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, json={"latency": 7})

    refused = propose_monitor(_proposal(), store=store, client=_client(handler), resolver=lambda host: ["10.0.0.5"])
    assert refused["preview"][0]["reason"] == "private_address_refused" and requests == []

    opted = propose_monitor({**_proposal(allow_private_network=True), "monitor_id": "proposed-lan"}, store=store,
                            client=_client(handler), resolver=lambda host: ["10.0.0.5"])
    assert opted["preview"][0]["number"] == 7.0 and len(requests) == 1


# --- L4.3 sources ------------------------------------------------------------------


def _feed(kind: str, source: dict, **extra) -> dict:
    from agent_runtime.lens.feed import read_feed

    return read_feed({"version": 1, "id": "local", "kind": kind, "interval_ms": 60_000, "source": source, **extra})


@pytest.fixture
def database(tmp_path):
    import sqlite3

    path = tmp_path / "app.sqlite3"
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE jobs (state TEXT)")
        connection.executemany("INSERT INTO jobs VALUES (?)", [("failed",), ("failed",), ("ok",)])
    connection.close()
    return path


def _rows(path) -> int:
    import sqlite3

    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    finally:
        connection.close()


def test_sql_readonly_reads_one_value_and_a_delete_never_reaches_sqlite(database):
    from agent_runtime.lens.sources import sql_readonly
    from agent_runtime.lens.wire_value import WireError, WireRefusal

    feed = _feed("sql_readonly", {"database": str(database),
                                  "query": "SELECT COUNT(*) FROM jobs WHERE state = 'failed'"})
    assert sql_readonly.read(feed, headers={}).value == 2.0
    many = {**feed, "source": {**feed["source"], "query": "SELECT state FROM jobs"}}
    assert sql_readonly.read(many, headers={}).reason.value == "ambiguous_series"

    with pytest.raises(WireError) as refused:
        _feed("sql_readonly", {"database": str(database), "query": "DELETE FROM jobs"})
    assert refused.value.code is WireRefusal.INVALID_STRING

    planted = {**feed, "source": {**feed["source"], "query": "DELETE FROM jobs"}}
    assert sql_readonly.read(planted, headers={}).reason.value == "statement_refused"
    hidden = {**feed, "source": {**feed["source"],
                                 "query": "WITH doomed AS (SELECT 1) DELETE FROM jobs RETURNING 1"}}
    assert sql_readonly.read(hidden, headers={}).value is None
    assert _rows(database) == 3


def test_a_command_outside_the_allow_list_never_runs_and_no_shell_reads_its_argv(tmp_path, monkeypatch):
    import sys

    from agent_runtime.lens.sources import command, read_feed_source
    from agent_runtime.lens.wire_value import WireError

    monkeypatch.chdir(tmp_path)
    allowed = [sys.executable, "-c", "print(7)", "x&echo>lens_marker"]
    feed = _feed("command_allowlisted", {"argv": allowed, "allow": [allowed], "extract": "$"})
    assert read_feed_source(feed, sealed=True).value == 7.0
    assert not (tmp_path / "lens_marker").exists(), "a shell ran the argv's tail"

    writer = [sys.executable, "-c", "open('lens_marker','w').write('1');print(1)"]
    with pytest.raises(WireError):
        _feed("command_allowlisted", {"argv": writer, "allow": [allowed], "extract": "$"})
    planted = {**feed, "source": {**feed["source"], "argv": writer}}
    assert command.read(planted, headers={}).reason.value == "command_refused"
    assert not (tmp_path / "lens_marker").exists()

    assert read_feed_source(feed).reason.value == "not_sealed", "a preview never runs a command"
    json_out = [sys.executable, "-c", "print('{\"queue\":{\"depth\":12}}')"]
    selected = _feed("command_allowlisted", {"argv": json_out, "allow": [json_out], "extract": "$.queue.depth"})
    assert read_feed_source(selected, sealed=True).value == 12.0


def test_prometheus_through_kube_proxy_reads_the_service_proxy_on_loopback():
    import httpx

    from agent_runtime.lens.sources import read_feed_source

    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"status": "success",
                                         "data": {"resultType": "scalar", "result": [1.0, "3"]}})

    feed = _feed("prometheus", {"via": "kube_proxy", "namespace": "monitoring", "service": "prometheus-k8s",
                                "port": 9090, "query": "up"})
    assert read_feed_source(feed, client=_client(handler)).value == 3.0
    assert seen == ["http://127.0.0.1:8001/api/v1/namespaces/monitoring/services/prometheus-k8s:9090/proxy"
                    "/api/v1/query?query=up"]
    loopback = _feed("prometheus", {"base_url": "http://127.0.0.1:9090", "query": "up"})
    assert read_feed_source(loopback, client=_client(handler)).reason.value == "private_address_refused"
