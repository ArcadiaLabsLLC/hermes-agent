"""Offline tests of the GenUI first-response A/B eval (``evals/genui_first_response_ab.py``).

The receipts are written through the runtime's OWN writers into a temp ``HERMES_HOME``
(``persist_mission_chat_turn``, ``persist_context_row``), so the reader is proven against
the shapes a QA serve persists, not against a hand-copied dict. No serve, no provider.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals import genui_first_response_ab as ab

ANSWER_TABLE = "| | Python | Rust |\n|---|---|---|\n| Speed | ok | fast |"


def _tool(seq: int, name: str, *, result: str = "", status: str = "completed") -> dict:
    return {"kind": "tool", "id": f"t{seq}", "turn_id": "turn1", "seq": seq, "name": name,
            "status": status, "tool_result": result}


def _answer(seq: int, text: str) -> dict:
    return {"kind": "segment", "id": f"s{seq}", "turn_id": "turn1", "seq": seq, "seg_type": "answer", "text": text}


#: The 2026-10-15 miss (QA serve 7e24ded80e): a Markdown table, tool_turns=0.
MISS = [_answer(1, ANSWER_TABLE)]
#: A hit: catalog read, then create; the reply carries the document's ID.
HIT = [
    _tool(1, "launcher_generated_list", result="components: Composition, Text"),
    _tool(2, "launcher_generated_create", result='{"document_id": "gdoc_42", "revision": 1}'),
    _answer(3, "Here is the comparison."),
]
#: Planted: a hermes-agent tool first, then a create — tool_turns>0 but NOT a first-tool hit.
PLANTED = [
    _tool(1, "skill_view", result="skill body"),
    _tool(2, "launcher_generated_create", result='{"document_id": "gdoc_43"}'),
    _answer(3, "Done."),
]


def _write_turn(home: Path, session_id: str, elements: list[dict], *, state: str = "completed") -> None:
    from agent_runtime.mission_chat_turns.journal import persist_mission_chat_turn

    with ab._home_scope(home, None):
        persist_mission_chat_turn(session_id=session_id, client_message_id="cm1", turn_id="turn1",
                                  elements=elements, state="running", write_ahead=True)
        if state != "running":
            persist_mission_chat_turn(session_id=session_id, client_message_id="cm1", turn_id="turn1",
                                      elements=elements, state=state)


def _guidance(text: str) -> str:
    return f"{ab.TOOL_GUIDANCE_BLOCK_HEADING}\n<!-- hermes-plugin-section-chars:{len(text)} -->\n\n{text}"


def _write_ctx(home: Path, context_id: str, *, session_id: str, guidance: str, per_tool: dict,
               provider: str = "openai-codex") -> None:
    from agent_runtime.prompt_observability.context_store import persist_context_row

    block = _guidance(guidance)
    row = {
        "context_id": context_id, "session_id": session_id, "turn_id": "turn1",
        "model_selection": {"effective_provider": provider, "effective_model": "m1"},
        "final_model_input": {
            "kind": "redaction_safe_final_model_input",
            "messages": [{"role": "system", "content": "# Stable\nfoo\n\n" + block + "\n"}],
            "system_prompt_sections": [{"kind": "stable", "name": "Stable Hermes foundation", "start_char": 0,
                                        "end_char": 10, "chars": 10,
                                        "blocks": [{"heading": "# Stable", "chars": 13},
                                                   {"heading": ab.TOOL_GUIDANCE_BLOCK_HEADING, "chars": len(block) + 1}]}],
            "tool_schema": {"final_model_tools": sorted(per_tool), "tool_count": len(per_tool),
                            "per_tool_chars": per_tool},
        },
    }
    with ab._home_scope(home, None):
        persist_context_row(row, store_catalog=lambda ref, rows: None)


PER_TOOL = {"launcher_generated_list": 300, "launcher_generated_create": 400, "terminal": 900}


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    path = tmp_path / "qa-home"
    path.mkdir()
    return path


# ── G1 reader ───────────────────────────────────────────────────────────────


def test_read_turn_scores_hit_miss_and_planted(home: Path) -> None:
    _write_turn(home, "s-miss", MISS)
    _write_turn(home, "s-hit", HIT)
    _write_turn(home, "s-planted", PLANTED)

    miss = ab.read_turn(home, "s-miss", "cm1")
    assert miss is not None and miss.tool_turns == 0 and miss.prose_only and not miss.is_hit
    hit = ab.read_turn(home, "s-hit", "cm1")
    assert hit is not None and hit.first_tool == "launcher_generated_list"
    assert hit.created_document_id == "gdoc_42" and hit.is_hit and hit.settled
    planted = ab.read_turn(home, "s-planted", "cm1")
    assert planted is not None and planted.tool_turns == 2 and planted.first_tool == "skill_view"
    assert planted.created_document_id == "gdoc_43"
    assert not planted.is_hit, "a hermes-agent tool first is a miss even when a create follows"
    assert ab.read_turn(home, "s-absent", "cm1") is None


def test_create_without_document_id_is_not_a_hit(home: Path) -> None:
    _write_turn(home, "s-refused", [_tool(1, "launcher_generated_create", result="invalid arguments", status="failed")])
    outcome = ab.read_turn(home, "s-refused", "cm1")
    assert outcome is not None and outcome.first_tool == "launcher_generated_create"
    assert outcome.created_document_id is None and not outcome.is_hit


def test_inflight_turn_is_not_settled(home: Path) -> None:
    _write_turn(home, "s-run", HIT, state="running")
    outcome = ab.read_turn(home, "s-run", "cm1")
    assert outcome is not None and not outcome.settled


def test_read_cost_and_find_context(home: Path) -> None:
    _write_ctx(home, "ctx_aaaa", session_id="s-hit", guidance="Compare things with launcher_generated_create.",
               per_tool=PER_TOOL)
    assert ab.find_context_id(home, session_id="s-hit", turn_id="turn1") == "ctx_aaaa"
    assert ab.find_context_id(home, session_id="s-other", turn_id="turn1") is None
    cost = ab.read_cost(home, "ctx_aaaa")
    assert cost is not None
    assert cost.per_tool_chars == {"launcher_generated_list": 300, "launcher_generated_create": 400}
    block = _guidance("Compare things with launcher_generated_create.")
    assert cost.guidance_chars == len(block) + 1
    assert cost.total_chars == len(block) + 1 + 700 and cost.tokens == cost.total_chars / 4
    assert cost.comparison_in_guidance is True and cost.guidance_sha256 and len(cost.guidance_sha256) == 64
    assert cost.provider == "openai-codex"
    assert ab.read_cost(home, "ctx_missing") is None


def _result(pid: str, kind: str, outcome, *, agent: str = "Amelia", cost=None) -> ab.PromptResult:
    return ab.PromptResult(prompt_id=pid, kind=kind, agent=agent, outcome=outcome, cost=cost, provider="p1")


def test_score_counts_hits_controls_and_unread() -> None:
    hit = ab.turn_outcome({"turn_id": "t", "state": "completed", "elements": HIT})
    miss = ab.turn_outcome({"turn_id": "t", "state": "completed", "elements": MISS})
    planted = ab.turn_outcome({"turn_id": "t", "state": "completed", "elements": PLANTED})
    results = [_result("P01", ab.COMPARISON, hit), _result("P02", ab.COMPARISON, miss),
               _result("P03", ab.COMPARISON, planted), _result("P04", ab.COMPARISON, None),
               _result("C1", ab.CONTROL, miss), _result("C2", ab.CONTROL, hit)]
    [cell] = ab.score(results)
    assert (cell.agent, cell.provider, cell.hits, cell.comparisons) == ("Amelia", "p1", 1, 4)
    assert cell.misses == ("P02", "P03", "P04") and cell.unread == ("P04",)
    assert (cell.controls_prose, cell.controls, cell.control_failures) == (1, 2, ("C2",))


def test_prompt_set_is_the_plans_fixed_set() -> None:
    data = json.loads((Path(ab.__file__).parent / "genui_first_response_prompts.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in data["comparisons"]] == [f"P{n:02d}" for n in range(1, 13)]
    assert [item["id"] for item in data["controls"]] == ["C1", "C2", "C3"]
    texts = " ".join(item["text"] for item in data["comparisons"] + data["controls"]).lower()
    assert "launcher_generated" not in texts and "generated." not in texts, "no prompt names a tool"


# ── G2 driver ───────────────────────────────────────────────────────────────

PROMPTS_PATH = Path(ab.__file__).parent / "genui_first_response_prompts.json"


def test_drive_opens_one_chat_per_prompt_per_agent() -> None:
    plan = ab.drive("A", ab.load_prompts(PROMPTS_PATH), ["Amelia", "Base"])
    news = [step for step in plan["steps"] if step["op"] == ab.OP_NEW]
    sends = [step for step in plan["steps"] if step["op"] == ab.OP_SEND]
    assert len(news) == 30 and len(sends) == 30
    assert len({step["session_ref"] for step in news}) == 30, "each prompt opens its own chat"
    opened: set[str] = set()
    sent: set[str] = set()
    for step in plan["steps"]:
        if step["op"] == ab.OP_NEW:
            opened.add(step["session_ref"])
        elif step["op"] == ab.OP_SEND:
            assert step["session_ref"] in opened, "a send goes into a chat opened before it"
            assert step["session_ref"] not in sent, "no chat carries a second prompt"
            sent.add(step["session_ref"])
    assert [step["step"] for step in plan["steps"]] == [f"s{n:03d}" for n in range(1, 91)]


def test_drive_multiplies_providers() -> None:
    plan = ab.drive("B", ab.load_prompts(PROMPTS_PATH), ["Base"], providers=["p1", "p2"])
    news = [step for step in plan["steps"] if step["op"] == ab.OP_NEW]
    assert len(news) == 30 and {step["args"]["provider"] for step in news} == {"p1", "p2"}


def test_collect_reads_sent_turns_back(home: Path) -> None:
    prompts = [("P01", ab.COMPARISON, "x"), ("P02", ab.COMPARISON, "y"), ("C1", ab.CONTROL, "z")]
    plan = ab.drive("A", prompts, ["Amelia"])
    _write_turn(home, "sid-1", HIT)
    _write_turn(home, "sid-3", MISS)
    _write_ctx(home, "ctx_bbbb", session_id="sid-1", guidance="g", per_tool=PER_TOOL, provider="p9")
    sends = {"Amelia/default/P01": {"session_id": "sid-1", "client_message_id": "cm1"},
             "Amelia/default/C1": {"session_id": "sid-3", "client_message_id": "cm1"}}
    results = ab.collect(home, plan, sends)
    assert [(r.prompt_id, r.kind) for r in results] == [("P01", "comparison"), ("P02", "comparison"), ("C1", "control")]
    assert results[0].outcome.is_hit and results[0].cost.context_id == "ctx_bbbb"
    assert results[0].provider_key == "p9" and results[1].outcome is None
    assert results[2].outcome.prose_only and results[2].cost is None


# ── G3 report ───────────────────────────────────────────────────────────────


def _cell(hits: int, controls_prose: int = 3, *, cost_chars: int | None = 4000,
          comparison_in_guidance: bool | None = True) -> ab.ArmScore:
    return ab.ArmScore(agent="Base", provider="p1", hits=hits, comparisons=12, misses=(), controls_prose=controls_prose,
                       controls=3, control_failures=() if controls_prose == 3 else ("C1",), unread=(),
                       cost_chars=cost_chars, comparison_in_guidance=comparison_in_guidance, create_wire_chars=180)


def test_bar_arithmetic() -> None:
    assert ab.cell_verdict(_cell(9))[0] == "FAIL"
    assert ab.cell_verdict(_cell(10))[0] == "PASS"
    assert ab.cell_verdict(_cell(12, controls_prose=2))[0] == "FAIL", "a control hit fails the arm"
    base = _cell(4, cost_chars=4000)
    assert ab.cell_verdict(_cell(10, cost_chars=4000 + 320), base) == ("PASS", 80.0)
    assert ab.cell_verdict(_cell(10, cost_chars=4000 + 324), base) == ("OVER COST", 81.0)
    assert ab.cell_verdict(_cell(10, cost_chars=None), base)[0] == "OVER COST", "an unread cost is never adopted"


def test_report_table_and_first_line() -> None:
    text = ab.report([_cell(10)], arm="B", baseline=[_cell(4)], baseline_arm="A", build="qa-123")
    assert "## Arm B vs baseline A" in text and "`qa-123`" in text
    assert "| Base | p1 | 10/12 |" in text and "| +0 |" in text and text.rstrip().splitlines()[-1].startswith("Bar:")
    assert "| PASS |" in text and "**First:**" not in text
    first = ab.report([_cell(3, comparison_in_guidance=False)], arm="A")
    assert "**First:**" in first and "(180 chars)" in first and "| FAIL |" in first


def test_cli_plan_collect_report_round_trip(home: Path, tmp_path: Path) -> None:
    plan_path, sends_path = tmp_path / "plan.json", tmp_path / "sends.json"
    results_path, report_path = tmp_path / "results.json", tmp_path / "report.md"
    assert ab.main(["plan", "--arm", "A", "--agent", "Base", "--prompts", str(PROMPTS_PATH), "--out", str(plan_path)]) == 0
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    sends = {}
    for index, step in enumerate(s for s in plan["steps"] if s["op"] == ab.OP_SEND):
        sid = f"sid-{index}"
        _write_turn(home, sid, HIT if step["kind"] == ab.COMPARISON else MISS)
        _write_ctx(home, f"ctx_{index:04d}", session_id=sid, guidance="compare", per_tool=PER_TOOL, provider="p1")
        sends[step["session_ref"]] = {"session_id": sid, "client_message_id": "cm1"}
    sends_path.write_text(json.dumps(sends), encoding="utf-8")
    assert ab.main(["collect", "--home", str(home), "--plan", str(plan_path), "--sends", str(sends_path),
                    "--wait-seconds", "0", "--build", "qa-1", "--out", str(results_path)]) == 0
    assert ab.main(["report", "--results", str(results_path), "--baseline", str(results_path),
                    "--out", str(report_path)]) == 0
    text = report_path.read_text(encoding="utf-8")
    assert "| Base | p1 | 12/12 | — | 3/3 |" in text and "| +0 |" in text and "| PASS |" in text
