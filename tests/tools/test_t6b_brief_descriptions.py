"""T6b — brief wire descriptions + details-on-demand (Context Cost Workstream).

Pins the invariants introduced by the description trims:
  * the wire ships a BRIEF description for every trimmed tool — either the
    registry schema itself (fork-owned registrations) or the eternia-harness
    ``llm_request`` middleware's rewrite of upstream's text
    (``tools.downstream_schema.brief_request_tools``);
  * the FULL text stays retrievable via tool_describe, plus the live (untrimmed)
    parameter schema;
  * tool_describe is injected into every resolved lane, independent of
    tool-search deferral.

These are behavior contracts (relations between wire brief and full docs), not
frozen byte snapshots — the exact byte totals are reported by the workstream doc,
not asserted here.
"""

import json

import pytest

from tools.downstream_schema import BRIEF_DESCRIPTIONS, brief_request_tools
from tools.registry import registry, discover_builtin_tools
from tools.tool_full_descriptions import FULL_TOOL_DESCRIPTIONS, full_tool_description
from tools.tool_search import dispatch_tool_describe, TOOL_DESCRIBE_NAME


@pytest.fixture(scope="module", autouse=True)
def _tools_discovered():
    discover_builtin_tools()


@pytest.fixture(autouse=True)
def _plugin_tools_discovered():
    """skill_search registers through the eternia-harness plugin (seam S2), and the
    hermetic conftest resets the plugin managers per test, so discover per test."""
    from hermes_cli.plugins import discover_plugins

    discover_plugins()


TRIMMED_TOOLS = sorted(set(FULL_TOOL_DESCRIPTIONS) | set(BRIEF_DESCRIPTIONS))


def _schema(name):
    entry = registry.get_entry(name)
    assert entry is not None, name
    return entry.schema or {}


def _wire(name):
    """The description the provider receives: the registry schema through the middleware."""
    request = {"tools": [{"type": "function", "function": _schema(name)}]}
    rewritten = brief_request_tools(request) or request
    return rewritten["tools"][0]["function"].get("description", "")


def _full(name):
    """What tool_describe serves: the mirror/captured text, else the registry's live text."""
    return full_tool_description(name) or _schema(name).get("description", "")


def test_mirror_and_briefs_cover_thirty_three_tools():
    """Every tool whose wire description T6b trimmed has a brief (mirror or middleware).

    34 was T6b's count after ``mission_goal_create`` retired; 33 since lane REDS3
    (2026-09-24) dropped ``vision_analyze``, whose upstream text (#97339) is now
    shorter than the brief was. The set splits disjoint: 9 mirror rows (fork-owned
    registrations) + 24 ``BRIEF_DESCRIPTIONS`` entries (read_file joined the
    middleware in lane REDS3).
    """
    assert not set(FULL_TOOL_DESCRIPTIONS) & set(BRIEF_DESCRIPTIONS)
    assert len(TRIMMED_TOOLS) == 33
    assert "mission_goal_create" not in TRIMMED_TOOLS


def test_full_tool_description_resolves_for_every_trimmed_tool():
    for name in TRIMMED_TOOLS:
        assert _full(name), f"{name}: empty full docs"


def test_wire_ships_brief_shorter_than_full_docs():
    """Each trimmed tool's on-the-wire description is no longer than the full docs
    tool_describe serves — and the lane-wide reduction is large.

    Every offender is collected before asserting: stopping at the first one hid
    three stale briefs (read_file, skill_search, vision_analyze) behind one red
    for three days (lane REDS3).
    """
    wire_total = 0
    full_total = 0
    offenders: list[str] = []
    for name in TRIMMED_TOOLS:
        if registry.get_entry(name) is None:
            offenders.append(f"{name}: not in the registry")
            continue
        wb = len(_wire(name).encode("utf-8"))
        fb = len(_full(name).encode("utf-8"))
        wire_total += wb
        full_total += fb
        if wb > fb:
            offenders.append(f"{name}: wire brief ({wb}) longer than full ({fb})")
    assert not offenders, "\n".join(offenders)
    # Aggregate cut is dramatic (the workstream target was >= ~68%).
    assert wire_total < full_total * 0.4, (wire_total, full_total)


def test_registry_keeps_upstream_text_for_middleware_briefed_tools():
    """The moved briefs never reach the registry: it carries upstream's text."""
    for name in ("clarify", "session_search", "write_file", "todo_list", "browser_navigate"):
        assert _schema(name)["description"] != BRIEF_DESCRIPTIONS[name], name
        assert _wire(name) == BRIEF_DESCRIPTIONS[name], name


def test_tool_describe_returns_full_docs_and_live_params():
    """tool_describe serves the full text + the untrimmed parameters."""
    for name in ("session_search", "browser_navigate", "execute_code"):
        schema = _schema(name)
        result = json.loads(dispatch_tool_describe(
            {"name": name}, current_tool_defs=[{"type": "function", "function": schema}]))
        assert "error" not in result, (name, result)
        assert result["description"] == _full(name)
        # The wire brief is shorter; tool_describe returns MORE.
        assert len(result["description"]) > len(_wire(name)), name
        # Parameters are never trimmed — live registry schema comes back.
        assert result["parameters"] == schema.get("parameters", {})


def test_skill_manage_full_docs_stay_profile_aware():
    """skill_manage's full docs name the profile-aware skills home.

    Upstream stopped interpolating the resolved directory at the 2026-09-25
    merge (``_skill_manage_description()`` takes no argument and says "the
    profile's skills directory or configured skills.create_dir"); the full doc
    follows upstream's live text rather than a path literal.
    """
    full = full_tool_description("skill_manage")
    assert "profile's skills directory" in full
    assert "skills.create_dir" in full


def test_shell_policy_left_the_terminal_wire_but_stays_in_full_docs():
    """The 'do not use cat/grep/sed' policy moved to the system prompt; it is
    gone from the terminal wire brief but preserved in the full docs."""
    wire = _wire("terminal")
    assert "Do NOT use cat/head/tail" not in wire
    full = full_tool_description("terminal")
    assert "Do NOT use cat/head/tail" in full


def test_tool_describe_injected_into_resolved_lane():
    import model_tools

    defs = model_tools.get_tool_definitions(
        enabled_toolsets=["session_search", "file"], quiet_mode=True
    )
    names = [d["function"]["name"] for d in defs]
    assert TOOL_DESCRIBE_NAME in names
    assert names.count(TOOL_DESCRIBE_NAME) == 1


def test_terminal_wire_brief_states_persistence_full_docs_keep_the_detail():
    """Moved from ``tests/tools/test_terminal_tool.py`` (seam Stage 2): the wire
    brief states cwd + env persist between calls; the virtualenv / re-source
    detail lives in the full docs (tool_describe)."""
    wire = (registry.get_entry("terminal").schema or {}).get("description", "")
    assert "cwd/exported env persist" in wire
    full = full_tool_description("terminal")
    assert "exported environment variables persist between calls" in full
    assert "activate a virtualenv" in full
    assert "once per session" in full
