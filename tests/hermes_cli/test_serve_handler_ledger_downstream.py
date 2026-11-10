"""Fork half of ``tests/hermes_cli/test_serve_handler_ledger.py`` (v0.23.1 release merge).

Upstream's ledger (``tests/hermes_cli/serve_handler_ledger.json``) stays at upstream's bytes so the
fork carries no edit in it; the fork's serve exposes more JSON-RPC verbs (``eternia.*``,
``session.recover`` / ``session.recovery.*`` / ``session.retire``), so the ledger the generator
renders for THIS tree lives in the fork-owned ``serve_handler_ledger_downstream.json``. Upstream's
whole-ledger node is a ``_fork_replaces`` row; this file asserts the same contract on the fork's copy.
Regenerate it with: ``python scripts/gen_serve_handler_ledger.py`` then move the written file here
(or ``scripts/gen_serve_handler_ledger.py --check`` against a temporary OUT).
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORK_LEDGER = ROOT / "tests" / "hermes_cli" / "serve_handler_ledger_downstream.json"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_serve_handler_ledger",
                                                  ROOT / "scripts" / "gen_serve_handler_ledger.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_fork_ledger_lists_every_live_handler():
    gen = _generator()
    facts = gen._facts()
    live = {row["handler"] for row in gen.rows(facts)}
    committed = FORK_LEDGER.read_text(encoding="utf-8-sig")
    listed = [row["handler"] for row in json.loads(committed)["handlers"]]
    assert len(listed) == len(set(listed))
    assert sorted(live - set(listed)) == [], "handlers with no fork ledger row: regenerate serve_handler_ledger_downstream.json"
    assert sorted(set(listed) - live) == [], "fork ledger rows for removed handlers: regenerate serve_handler_ledger_downstream.json"
    assert committed == gen.render(facts), "serve_handler_ledger_downstream.json is stale"


def test_upstreams_ledger_is_a_subset_of_the_fork_ledger():
    """Every handler upstream lists is still served by the fork (the fork only adds verbs)."""
    upstream = {row["handler"] for row in json.loads(
        (ROOT / "tests" / "hermes_cli" / "serve_handler_ledger.json").read_text(encoding="utf-8-sig"))["handlers"]}
    fork = {row["handler"] for row in json.loads(FORK_LEDGER.read_text(encoding="utf-8-sig"))["handlers"]}
    assert sorted(upstream - fork) == []
