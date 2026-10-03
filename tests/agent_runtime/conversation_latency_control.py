"""Read-only prerequisites and native signature evidence for the instance probe."""
from copy import deepcopy
from functools import wraps
import json
import os


def require_instance_registry():
    from agent_runtime.persona_chat_continuity import persona_chat_runtime_registry

    registry = persona_chat_runtime_registry()
    assert registry is not None, "Probe serve did not initialize the resident registry"
    return registry


def require_same_root(record, expected_root):
    root = record.get("root_chat_session_id")
    assert root and root == expected_root, "Probe turn changed or omitted its chat root"
    return root


class InstanceProbeControl:
    def __init__(self, record_property, monkeypatch):
        from agent_runtime import mission_chat_turn_context as context

        self.registry = require_instance_registry()
        self.configs = {}
        self.previous_config = None
        self.configured_files = {}
        self.record_property = record_property
        original = context.mission_chat_runtime_signature_components

        @wraps(original)
        def observe_signature(**kwargs):
            result = original(**kwargs)
            self.configs[kwargs["session_id"]] = deepcopy(kwargs["session_model_config"])
            return result

        monkeypatch.setattr(context, "mission_chat_runtime_signature_components", observe_signature)
        proof = {"registry_present": True, "serve_pid": os.getpid()}
        record_property("instance_probe_boot", json.dumps(proof, sort_keys=True))
        print("INSTANCE_PROBE_BOOT " + json.dumps(proof, sort_keys=True), flush=True)

    def opened(self, target, home):
        from hermes_constants import get_hermes_home

        assert target["session_id"], "Probe opened no chat root"
        self.root = target["session_id"]
        self.configured_files = {
            path: path.read_bytes()
            for path in {home / "config.yaml", get_hermes_home() / "config.yaml"}
        }

    def before_turn(self):
        assert require_instance_registry() is self.registry, "Probe replaced its resident registry"
        assert all(path.read_bytes() == content for path, content in self.configured_files.items()), (
            "Probe changed its root or profile configuration"
        )

    def record_turn(self, target, turn):
        from agent_runtime.mission_chat_turns import mission_chat_turn_record

        self.before_turn()
        record = mission_chat_turn_record(session_id=target["session_id"], client_message_id=turn)
        root = require_same_root(record, self.root)
        expected_reuse = 0 if turn == "cold" else 1
        assert record["profile_timing"]["resident_actor_reused"] == expected_reuse
        agent = self.registry._entries[root].agent
        assert agent.session_prompt_tokens == 12
        assert agent.session_completion_tokens == 3
        assert agent._usage_anchor["prompt_tokens"] == 12
        assert agent._usage_anchor["completion_tokens"] == 3
        assert agent._usage_anchor == agent._session_db.get_session_model_config_value(
            record["active_session_id"], "_usage_anchor", None
        )
        assert root in self.configs, "Probe did not observe the native runtime signature"
        current = self.configs[root]
        previous = self.previous_config
        changed = [] if previous is None else sorted(
            key for key in current.keys() | previous.keys() if current.get(key) != previous.get(key)
        )
        proof = {
            "root_chat_session_id": root,
            "active_session_id": record.get("active_session_id"),
            "registry_same": True,
            "config_files_unchanged": True,
            "root_model_config_changed_fields": changed,
            "resident_actor_reused": record["profile_timing"]["resident_actor_reused"],
            "per_turn_usage_verified": True,
            "durable_usage_anchor_verified": True,
        }
        self.previous_config = current
        self.record_property(f"{turn}_control", json.dumps(proof, sort_keys=True))
        print(f"INSTANCE_PROBE_TURN {turn} " + json.dumps(proof, sort_keys=True), flush=True)
