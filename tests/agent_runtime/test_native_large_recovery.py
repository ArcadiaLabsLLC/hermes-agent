"""A response larger than the disposable replay ring remains recoverable."""
import json
import random
import time

import pytest

from agent_runtime.conversations.model import ConversationScope
from agent_runtime.conversations.service import ConversationService
from tests.agent_runtime.native_recovery_provider import RecoveryProvider
from tests.agent_runtime.test_native_recovery_roundtrip import until


@pytest.mark.timeout(180)
@pytest.mark.parametrize("compute", [False, True], ids=["inline", "compute-child"])
def test_large_terminal_response_reopens_after_worker_and_service_restart(tmp_path, compute):
    home = tmp_path / "profile"
    home.mkdir()
    text = random.Random(17).randbytes(5 * 1024 * 1024).hex()
    provider = RecoveryProvider(text=text)
    provider.configure(home, compute=compute)
    service = ConversationService(tmp_path, "isolated", profile_home=lambda _: home)
    scope = ConversationScope("operator", "account", "profile")
    def open_():
        return service.open(scope, key="large-chat", cwd=str(tmp_path), expected_home=str(home))
    try:
        opened = open_()
        sid, epoch = opened["session_id"], opened["epoch"]
        service.send(scope, sid, "original", {"text": "Ask whether to continue.", "images": []})
        pending = until(open_, lambda p: bool(p["recovery"].get("open_requests")))
        question = pending["recovery"]["open_requests"][0]
        service.respond(scope, sid, question["id"], {"answer": "Yes"})
        provider.release.set()
        def outcome():
            page = open_()
            return {"turn": page["turn"], "execution": page["recovery"].get("execution"),
                    "inflight": page["recovery"].get("inflight_position"),
                    "messages": page["recovery"].get("message_count")}
        until(outcome, lambda p: p["turn"]["state"] == "completed")
        recovered = service.read(scope, sid, 0, "original", epoch=epoch)
        assert recovered["recovery"]["execution"]["status"] == "complete"
        assert recovered["turn"]["state"] == "completed"
        service.close()
        service = ConversationService(tmp_path, "isolated", profile_home=lambda _: home)
        reopened = open_()
        assert reopened["session_id"] == sid and reopened["epoch"] != epoch
        assert reopened["turn"]["state"] == "completed"
        started = time.monotonic()
        pages = 0
        index, offset, rows = 0, 0, {}
        while True:
            page = service.history(scope, sid, reopened["recovery"]["history"], index, offset)
            pages += 1
            for chunk in page["chunks"]:
                prior = rows.get(chunk["index"], "")
                assert len(prior) == chunk["offset"]
                rows[chunk["index"]] = prior + chunk["data"]
            index, offset = page["message_index"], page["offset"]
            if not page["more"]:
                break
        messages = [json.loads(row) for row in rows.values()]
        answers = [m["text"] for m in messages if m["role"] == "assistant"]
        assert answers == [text + " after release"]
        assert len(provider.requests) == 2
        print(f"history: {len(text)} characters, {pages} pages, {time.monotonic() - started:.3f}s")
    finally:
        provider.release.set()
        service.close()
        provider.close()
