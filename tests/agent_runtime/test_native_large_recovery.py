"""A response larger than the disposable replay ring remains recoverable, across an engine restart.

Driven on the in-process engine directly (``engine_session``): the profile-scoped conversation service that
used to carry it is retired (RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT); the recovery it
pins is the gateway's. The reopened engine is a new worker generation, so its replay epoch differs
(``recovery_history._epoch`` carries ``serving_worker``), and closing the last in-process worker stops the
compute host (``in_process_peer.stop_compute_host``) — the compute-child case reopens on a fresh one.
"""
import json
import random
import time

import pytest

from tests.agent_runtime.engine_session import EngineSession, until
from tests.agent_runtime.native_recovery_provider import RecoveryProvider


@pytest.mark.slow_native
@pytest.mark.timeout(180)
@pytest.mark.parametrize("compute", [False, True], ids=["inline", "compute-child"])
def test_large_terminal_response_reopens_after_an_engine_restart(tmp_path, compute):
    from hermes_cli.profiles import get_profile_dir

    home = get_profile_dir("profile")  # a canonical profile home: the in-process worker serves by name
    home.mkdir(parents=True)
    text = random.Random(17).randbytes(5 * 1024 * 1024).hex()
    provider = RecoveryProvider(text=text)
    provider.configure(home, compute=compute)
    engine = EngineSession(home, cwd=str(tmp_path))
    try:
        epoch = engine.recover()["epoch"]
        engine.submit("Ask whether to continue.", "large-execution")
        pending = until(engine.recover, lambda r: any(q["method"] == "clarify" for q in r.get("open_requests", ())))
        question = next(q for q in pending["open_requests"] if q["method"] == "clarify")
        assert engine.answer(question["id"], {
            "answers": {question["params"]["questions"][0]["qid"]: "Yes"}})["status"] == "ok"
        provider.release.set()
        # Native rendering/persistence of 10 MiB takes longer under suite CPU load.
        done = until(lambda: engine.recover("large-execution"),
                     lambda r: (r.get("execution") or {}).get("status") == "complete", timeout=90)
        assert done["execution"]["id"] == "large-execution"
        stored = engine.stored
        engine.close()
        engine = EngineSession(home, resume=stored)
        reopened = engine.recover("large-execution")
        assert reopened["epoch"] != epoch
        assert reopened["execution"]["status"] == "complete"
        started = time.monotonic()
        messages = [json.loads(row) for row in engine.history(reopened["history"])]
        answers = [m["text"] for m in messages if m["role"] == "assistant"]
        assert answers == [text + " after release"]
        assert len(provider.requests) == 2
        print(f"history: {len(text)} characters, {time.monotonic() - started:.3f}s")
    finally:
        provider.release.set()
        engine.close()
        provider.close()
