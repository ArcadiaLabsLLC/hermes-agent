"""Real native and compute execution: reopen questions/streaming, answer, exact Stop.

Driven on the in-process engine directly (``engine_session``); the profile-scoped conversation service that
used to carry it is retired (RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT).
"""
import pytest

from tests.agent_runtime.engine_session import EngineSession, until
from tests.agent_runtime.native_recovery_provider import RecoveryProvider

pytestmark = pytest.mark.timeout(120)


@pytest.mark.parametrize("compute", [False, True], ids=["inline", "compute-child"])
def test_reopen_live_question_and_stream_then_stop_same_execution(tmp_path, compute):
    from hermes_cli.profiles import get_profile_dir

    home = get_profile_dir("profile")  # a canonical profile home: the in-process worker serves by name
    home.mkdir(parents=True)
    provider = RecoveryProvider()
    provider.configure(home, compute=compute)
    engine = EngineSession(home, cwd=str(tmp_path))
    try:
        engine.submit("Ask whether to continue.", "original")
        recovered = until(engine.recover, lambda r: any(q["method"] == "clarify" for q in r.get("open_requests", ())))
        question = next(q for q in recovered["open_requests"] if q["method"] == "clarify")
        answer = {"answers": {question["params"]["questions"][0]["qid"]: "Yes"}}
        assert engine.answer(question["id"], answer)["status"] == "ok"
        assert provider.partial.wait(10)
        streamed = until(engine.recover, lambda r: r.get("inflight_position", {}).get("assistant", 0) > 0)
        position = streamed["inflight_position"]
        assert position["execution_id"] == "original"
        prefix = engine.inflight(execution_id="original", field="assistant", through=position["assistant"],
                                 offset=0, revision=position["revision"])
        assert prefix["text"].strip() == "Recovered prefix 🌍"
        assert engine.stop("original")["status"] == "interrupted"
        provider.release.set()
        settled = until(lambda: engine.recover("original"),
                        lambda r: (r.get("execution") or {}).get("status") not in {None, "running"})
        assert settled["execution"]["id"] == "original" and settled["execution"]["status"] == "interrupted"
        assert len(provider.requests) == 2, "reconstruction must not execute another prompt"
    finally:
        provider.release.set()
        engine.close()
        provider.close()
