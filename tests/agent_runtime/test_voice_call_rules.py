"""RT-FU-ETERNIAS-AGENT-CALL-CAN-USE-HERMES-OWN-INTERRUPT-RULES: a call client reads the user's settings from hermes.

``runtime.speech.call_settings`` (read tier) answers ``voice.barge_in``, the grace, the multiplier and
the stop phrases, and the rules revision a client port must match. The fork may not import upstream's
private readers, so ``agent_runtime.voice_call_rules`` reads the same settings once more; these tests
hold it equal to upstream's two readers (``tui_gateway/methods_voice.py`` ``_fd_barge_params`` and the
``barge_in`` arm check, ``tools/voice_mode_transcript.py`` ``_load_voice_stop_phrases``) over every
shape they handle, and drive the method through the real dispatcher.

Killing mutations (each watched red):
* ``_grace_ms`` without ``max(0, ...)`` -> the negative-grace case parts from upstream;
* ``_threshold_multiplier`` returning 3.0 for a malformed value -> the parity case;
* ``_stop_phrases`` without ``.lower()`` -> the parity case;
* ``call_settings`` reading ``voice.get("barge_in", False)`` -> the default case;
* the method registered at ``TIER_CONSOLE`` -> the tier case;
* the method answered through ``_speech_answer`` (which imports the speech service) -> the phone case;
* ``_threshold_multiplier`` without the ``math.isfinite`` check, or ``_grace_ms`` without
  ``OverflowError`` -> the non-finite case.
"""

from __future__ import annotations

import pytest

from agent_runtime.serve_rpc import RpcContext, handle_request
from agent_runtime.voice_call_rules import RULE_VECTORS_REVISION, call_settings

#: Every ``voice`` block shape the upstream readers handle: valid, missing, empty, malformed, wrong-typed.
VOICE_BLOCKS = [
    {},
    {"barge_in": True, "barge_in_grace_seconds": 0.5, "barge_in_threshold_multiplier": 3.0, "stop_phrases": ["stop"]},
    {"barge_in": False},
    {"barge_in": None},
    {"barge_in": 0},
    {"barge_in": "no"},  # a non-empty string is truthy upstream too
    {"barge_in_grace_seconds": 1.25},
    {"barge_in_grace_seconds": "0.8"},
    {"barge_in_grace_seconds": -2},
    {"barge_in_grace_seconds": "soon"},
    {"barge_in_grace_seconds": None},
    {"barge_in_grace_seconds": [1]},
    {"barge_in_grace_seconds": 0},
    {"barge_in_threshold_multiplier": 4.5},
    {"barge_in_threshold_multiplier": "6"},
    {"barge_in_threshold_multiplier": 0},
    {"barge_in_threshold_multiplier": None},
    {"barge_in_threshold_multiplier": ""},
    {"barge_in_threshold_multiplier": "loud"},
    {"barge_in_threshold_multiplier": {"x": 1}},
    {"stop_phrases": []},
    {"stop_phrases": "Hang Up"},
    {"stop_phrases": ["  Stop ", "HANG UP", "", "  ", 7, 2.5, None, ["nested"], {"k": 1}]},
    {"stop_phrases": None},
    {"stop_phrases": {"stop": True}},
    {"stop_phrases": 42},
]


def _upstream_barge(voice: dict) -> tuple[bool, float, int]:
    """What the gateway's own full-duplex listener reads from this block."""
    from tui_gateway import methods_voice

    mult, grace_ms = methods_voice._fd_barge_params(voice)
    return bool(voice.get("barge_in", True)), mult, grace_ms


def _upstream_stop_phrases(voice: dict, monkeypatch) -> tuple:
    from tools import voice_mode_transcript

    monkeypatch.setattr(voice_mode_transcript, "_voice_config", lambda: voice)
    return voice_mode_transcript._load_voice_stop_phrases()


@pytest.mark.parametrize("voice", VOICE_BLOCKS, ids=[repr(v)[:60] for v in VOICE_BLOCKS])
def test_the_settings_read_as_hermes_own_voice_mode_reads_them(voice, monkeypatch):
    ours = call_settings(voice)
    assert (ours["barge_in"], ours["threshold_multiplier"], ours["grace_ms"]) == _upstream_barge(voice)
    assert tuple(ours["stop_phrases"]) == _upstream_stop_phrases(voice, monkeypatch)


def test_the_upstream_arm_check_reads_barge_in_as_this_does(monkeypatch):
    """``_arm_barge_listener_if_enabled`` is the gateway's one ``barge_in`` decision."""
    from tui_gateway import methods_voice

    armed: list[bool] = []
    monkeypatch.setattr(methods_voice, "_voice_mode_enabled", lambda: True)
    monkeypatch.setattr(methods_voice, "_arm_full_duplex_listener", lambda: armed.append(True))
    for voice in VOICE_BLOCKS:
        armed.clear()
        monkeypatch.setattr(methods_voice, "_voice_cfg_dict", lambda voice=voice: voice)
        methods_voice._arm_barge_listener_if_enabled()
        assert bool(armed) is call_settings(voice)["barge_in"], voice


def test_an_unset_voice_block_answers_hermes_defaults(monkeypatch):
    import hermes_cli.config

    for loaded in ({}, {"voice": None}, {"voice": "on"}, {"voice": ["x"]}, None):
        monkeypatch.setattr(hermes_cli.config, "load_config_readonly", lambda loaded=loaded: loaded)
        assert call_settings() == {
            "barge_in": True, "grace_ms": 500, "threshold_multiplier": 0.0, "stop_phrases": ["stop"],
            "rules_revision": RULE_VECTORS_REVISION,
        }, loaded


def test_the_loaded_config_is_what_is_read(monkeypatch):
    import hermes_cli.config

    monkeypatch.setattr(hermes_cli.config, "load_config_readonly", lambda: {"voice": {
        "barge_in": False, "barge_in_grace_seconds": 0.25, "barge_in_threshold_multiplier": 4.0,
        "stop_phrases": ["Goodbye"]}})
    assert call_settings() == {"barge_in": False, "grace_ms": 250, "threshold_multiplier": 4.0,
                               "stop_phrases": ["goodbye"], "rules_revision": RULE_VECTORS_REVISION}


def test_the_serve_answers_the_settings_at_the_read_tier(monkeypatch):
    import hermes_cli.config
    from agent_runtime.serve_rpc.registry import method_tier

    monkeypatch.setattr(hermes_cli.config, "load_config_readonly", lambda: {"voice": {"barge_in_grace_seconds": 1}})
    frame = handle_request({"jsonrpc": "2.0", "id": 7, "method": "runtime.speech.call_settings", "params": {}},
                           RpcContext(connection_key="conn-a", transport="socket"))
    assert frame["result"] == {"barge_in": True, "grace_ms": 1000, "threshold_multiplier": 0.0,
                               "stop_phrases": ["stop"], "rules_revision": RULE_VECTORS_REVISION}
    assert method_tier("runtime.speech.call_settings") == "read"


@pytest.mark.parametrize(("voice", "expected"), [
    ({"barge_in_threshold_multiplier": "nan"}, {"threshold_multiplier": 0.0}),
    ({"barge_in_threshold_multiplier": float("inf")}, {"threshold_multiplier": 0.0}),
    ({"barge_in_threshold_multiplier": "-inf"}, {"threshold_multiplier": 0.0}),
    ({"barge_in_grace_seconds": "inf"}, {"grace_ms": 500}),
    ({"barge_in_grace_seconds": float("nan")}, {"grace_ms": 500}),
])
def test_a_non_finite_setting_reads_as_malformed_so_the_answer_is_always_json(voice, expected):
    """Upstream's reader raises on an infinite grace and passes a NaN multiplier through; a served
    answer must stay valid JSON, so both read as malformed (the default)."""
    import json

    answer = call_settings(voice)
    assert {key: answer[key] for key in expected} == expected
    json.loads(json.dumps(answer, allow_nan=False))


def test_a_phone_without_the_speech_service_still_answers(monkeypatch):
    """``bundled-phone.yaml`` switches ``agent_runtime.speech_service`` off; the call settings never need it."""
    import sys

    import hermes_cli.config

    monkeypatch.setattr(hermes_cli.config, "load_config_readonly", lambda: {})
    monkeypatch.setitem(sys.modules, "agent_runtime.speech_service", None)  # import -> ImportError
    frame = handle_request({"jsonrpc": "2.0", "id": 9, "method": "runtime.speech.call_settings", "params": {}},
                           RpcContext(connection_key="conn-a", transport="socket"))
    assert frame.get("result", {}).get("barge_in") is True, frame


def test_a_config_that_cannot_be_read_is_a_handler_failure_naming_only_its_class(monkeypatch):
    import hermes_cli.config

    def broken():
        raise OSError("/home/someone/.hermes/config.yaml: permission denied")

    monkeypatch.setattr(hermes_cli.config, "load_config_readonly", broken)
    frame = handle_request({"jsonrpc": "2.0", "id": 8, "method": "runtime.speech.call_settings", "params": {}},
                           RpcContext(connection_key="conn-a", transport="socket"))
    assert frame["error"]["data"]["reason"] == "handler_failed"
    assert frame["error"]["data"]["error_class"] == "OSError"
    assert "someone" not in str(frame)
