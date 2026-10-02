"""Real instance RPC -> agent -> loopback provider -> reconstructed history."""
import json
import time

import pytest

from tests.agent_runtime.conversation_latency_probe import local_profile, runtime_probe, instance_target
from tests.agent_runtime.test_native_conversation_roundtrip import Provider
from tests.agent_runtime.test_operator_reviewed_input import reviewed_prompt


@pytest.mark.timeout(100)
@pytest.mark.parametrize("native_vision", [False, True])
def test_reviewed_input_reaches_provider_and_reopens_without_resubmission(monkeypatch, native_vision):
    from hermes_cli.config import atomic_config_write
    from hermes_constants import get_hermes_home
    import yaml

    prompt = reviewed_prompt()
    prompt["text"] += "reviewed-end-marker"
    with local_profile(monkeypatch) as home:
        for destination in (home, get_hermes_home()):
            path = destination / "config.yaml"
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            config["model"]["supports_vision"] = native_vision
            if not native_vision:
                config["auxiliary"] = {"vision": {"provider": "custom:local-test", "model": "test-model"}}
            atomic_config_write(path, config)
        with runtime_probe() as probe:
            target = instance_target(probe, home)
            sent = probe.call("runtime.operator.conversation.message", **target,
                              turn_request_id="reviewed", prompt=prompt)
            assert sent["accepted"]
            deadline = time.monotonic() + 50
            while True:
                page = probe.call("runtime.operator.conversation.read", **target,
                                  turn_request_id="reviewed")
                if page["delivery_observed"] and not page["active_turns"] and not page["delivery_pending"]:
                    break
                assert time.monotonic() < deadline, page
                time.sleep(.05)
            assert any(row["text"] == "Local native answer" for row in page["messages"]), page
        chats = [body for _, body in Provider.requests if body.get("stream")]
        assert len(chats) == 1, "Reviewed content must execute once"
        user = next(row for row in chats[0]["messages"]
                    if row["role"] == "user" and "reviewed-end-marker" in json.dumps(row))
        if native_vision:
            assert isinstance(user["content"], list)
            image = next(part for part in user["content"] if part["type"] == "image_url")
            assert image["image_url"]["url"] == "data:image/png;base64," + prompt["images"][0]["data"]
            text = next(part["text"] for part in user["content"] if part["type"] == "text")
        else:
            text = user["content"]
            assert "The user attached an image" in text
            assert "Local native answer" in text
        assert prompt["text"] in text
        with runtime_probe() as probe:
            recovered = probe.call("runtime.operator.conversation.read", **target)
            assert recovered["messages"] == page["messages"]
            assert not recovered["active_turns"]
        assert len([body for _, body in Provider.requests if body.get("stream")]) == 1
