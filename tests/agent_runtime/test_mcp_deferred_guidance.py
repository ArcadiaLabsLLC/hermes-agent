from types import SimpleNamespace
from agent_runtime.mcp_admission.outcomes import _admitted_clause
from tools.downstream_schema import promoted_brief


def test_admission_states_the_admitted_servers_without_claiming_eager_membership():
    """Facts only (owner ruling L2.12): the deferred route rides the capability block's
    deferred line, so the admitted clause names the servers and nothing else."""
    line = _admitted_clause(SimpleNamespace(server_names=("launcher_qa", "dart")), denied_servers=set())
    assert line == " Admitted on this turn: launcher_qa, dart."
    assert "ARE in your tool list" not in line


def test_qa_brief_routes_full_manual_only_when_description_was_cut():
    sentence = "Capture the selected application's window without changing its state."
    short = promoted_brief({"name": "mcp_launcher_qa_screenshot_window", "description": sentence})
    long = promoted_brief({"name": "mcp_launcher_qa_screenshot_window", "description": sentence + " Read additional capture requirements here."})
    assert short["description"] == sentence
    assert "mcp_launcher_qa_get_tool_manual" in long["description"]
    assert "tool_describe" not in long["description"]
