"""``runtime.text.summarize`` — a summary through the user's own model (RT-AUX-SUMMARIZE).

The model is a fake behind ``text_summary._plugin_llm`` (the harness plugin's ``ctx.llm``); no test
reaches a provider or the network. Each check names its killing mutation; the reds are recorded in
the commit that added this file.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import text_summary
from agent_runtime.serve_rpc import handle_request


class _FakeLlm:
    def __init__(self, text="- one\n- two", raise_with=None):
        self.text, self.raise_with, self.calls = text, raise_with, []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_with is not None:
            raise self.raise_with
        return SimpleNamespace(text=self.text, model="m-1", provider="p-1")


@pytest.fixture
def llm(monkeypatch):
    fake = _FakeLlm()
    monkeypatch.setattr(text_summary, "_plugin_llm", lambda: fake)
    return fake


def _call(params):
    return handle_request({"jsonrpc": "2.0", "id": 7, "method": "runtime.text.summarize", "params": params})


def _lines(count, size=10):
    return [{"at": f"t{i}", "speaker": f"s{i}", "text": f"line{i:05d}" + "x" * size} for i in range(count)]


def test_a_summary_answers_text_and_who_answered_it(llm):
    # Kill: drop ``"provider"`` from summarize's result -> the equality reds.
    frame = _call({"task": "message_digest", "lines": _lines(3), "max_bullets": 4, "locale": "pt-BR"})
    assert frame["result"] == {"contract": 1, "text": "- one\n- two", "model": "m-1", "provider": "p-1",
                               "truncated": False}
    (call,) = llm.calls
    assert call["task"] == "message_digest"
    prompt = call["messages"][1]["content"]
    assert "[t2] s2: line00002" in prompt and "at most 4 short bullets" in prompt and "pt-BR" in prompt


def test_an_over_cap_window_keeps_the_newest_lines_and_says_so(llm):
    # Kill: ``_newest_within`` walks ``lines`` oldest-first -> the newest line is the one dropped, red.
    lines = _lines(80, size=1_000)
    frame = _call({"task": "message_digest", "lines": lines})
    assert frame["result"]["truncated"] is True
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "line00079" in prompt and "line00000" not in prompt
    transcript = prompt.split("<transcript>\n", 1)[1].rsplit("\n</transcript>", 1)[0]
    assert len(transcript) <= text_summary.INPUT_CHAR_LIMIT
    # Positive control: the same lines under the cap are all sent, and truncated is False.
    llm.calls.clear()
    frame = _call({"task": "message_digest", "lines": lines[:50]})
    assert frame["result"]["truncated"] is False and "line00000" in llm.calls[0]["messages"][1]["content"]


def test_no_model_set_up_is_its_own_reason(monkeypatch):
    # Kill: ``_unavailable_reason`` answers None -> the reason is handler_failed, red.
    from agent.auxiliary_unavailable import AuxiliaryClientUnavailable

    monkeypatch.setattr(text_summary, "_plugin_llm", lambda: _FakeLlm(raise_with=AuxiliaryClientUnavailable("x")))
    frame = _call({"task": "message_digest", "lines": _lines(2)})
    assert frame["error"]["data"] == {"reason": "model_unavailable"}
    # Positive control: any other failure is handler_failed with the class name only.
    monkeypatch.setattr(text_summary, "_plugin_llm", lambda: _FakeLlm(raise_with=RuntimeError("secret body")))
    frame = _call({"task": "message_digest", "lines": _lines(2)})
    assert frame["error"]["data"]["reason"] == "handler_failed"
    assert frame["error"]["data"]["error_class"] == "RuntimeError" and "secret" not in str(frame)


@pytest.mark.parametrize("params, reason", [
    ({"task": "other", "lines": _lines(1)}, "task_unknown"),
    ({"task": "message_digest", "lines": []}, "lines_empty"),
    ({"task": "message_digest", "lines": [{"speaker": "a", "text": " "}]}, "line_text_invalid"),
    ({"task": "message_digest", "lines": [{"speaker": "", "text": "x"}]}, "line_speaker_invalid"),
    ({"task": "message_digest", "lines": _lines(1), "max_bullets": 11}, "max_bullets_invalid"),
    ({"task": "message_digest", "lines": _lines(1), "max_bullets": True}, "max_bullets_invalid"),
    ({"task": "message_digest", "lines": _lines(1), "locale": "english please"}, "locale_invalid"),
    ({"task": "message_digest", "lines": [{"speaker": "a", "text": "y" * 8_001}]}, "line_text_too_long"),
])
def test_bad_params_are_refused_before_any_model_call(llm, params, reason):
    # Kill: drop the ``max_bullets`` range check -> the 11 case reaches the model, red.
    frame = _call(params)
    assert frame["error"]["code"] == -32602 and frame["error"]["data"]["reason"] == reason
    assert llm.calls == []


def test_the_digest_task_inherits_compressions_route():
    # Kill: drop ``inherit_from=task.inherit_from`` from register_summary_tasks -> red.
    registered, unloads = [], []
    ctx = SimpleNamespace(
        register_auxiliary_task=lambda key, **kw: registered.append((key, kw)),
        on_unload=unloads.append, llm=object())
    text_summary.register_summary_tasks(ctx)
    assert [(key, kw["inherit_from"]) for key, kw in registered] == [("message_digest", "compression")]
    assert text_summary._plugin_contexts[text_summary._home_key()] is ctx
    unloads[0]()
    assert text_summary._home_key() not in text_summary._plugin_contexts
