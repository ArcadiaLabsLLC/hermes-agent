"""D1.08 S3 — the CLI verb runner ``persona slots`` and ``workspace slots`` share."""

from __future__ import annotations

import argparse
import json

import pytest

from agent_runtime.persona_slots import SlotAssignmentRefused
from agent_runtime.workspace_slot_env import SlotEnvRefused
from agent_runtime.workspace_slots import SlotRefused
from hermes_cli.harness_parts.persona import slots_commands
from hermes_cli.harness_parts import workspace_slots_commands
from hermes_cli.harness_parts.verb_runner import run_refusing_verb

ARGS = argparse.Namespace(json=True)


def _raise(exc):
    def action():
        raise exc

    return action


def _envelope(capsys) -> dict:
    out = capsys.readouterr()
    text = (out.out or out.err).strip()
    return json.loads(text[text.index("{"):])


def test_a_payload_prints_its_kind_envelope_and_exits_zero(capsys):
    assert run_refusing_verb(ARGS, "workspace_slots", lambda: {"slots": []}, refusals=(SlotRefused,)) == 0
    assert _envelope(capsys)["kind"] == "workspace_slots"


@pytest.mark.parametrize(
    "runner, exc",
    [
        (slots_commands._run_slot_verb, SlotAssignmentRefused("slot_unknown", "no slot 'x'")),
        (workspace_slots_commands._run_workspace_slot_verb, SlotRefused("slot_unknown", "no slot 'x'")),
        (workspace_slots_commands._run_workspace_slot_verb, SlotEnvRefused("slot_unknown", "no slot 'x'")),
    ],
)
def test_each_listed_refusal_is_invalid_payload_with_reason_and_detail(capsys, runner, exc):
    code = runner(ARGS, "k", _raise(exc))

    assert code != 0
    envelope = _envelope(capsys)
    assert envelope["error"]["code"] == "invalid_payload"
    assert envelope["error"]["message"] == "slot_unknown: no slot 'x'"


def test_a_plain_input_error_keeps_its_own_text_on_the_workspace_verbs(capsys):
    code = workspace_slots_commands._run_workspace_slot_verb(ARGS, "k", _raise(ValueError("--env expects KEY=VALUE")))

    assert code != 0
    assert _envelope(capsys)["error"]["message"] == "--env expects KEY=VALUE"


def test_an_unlisted_exception_propagates():
    """Killing mutation: catch ``Exception`` in ``run_refusing_verb`` → this
    raise is swallowed into an envelope and the test fails."""

    with pytest.raises(RuntimeError, match="store down"):
        run_refusing_verb(ARGS, "k", _raise(RuntimeError("store down")), refusals=(SlotRefused,))
    # A ValueError the persona lane does not list is not its refusal either.
    with pytest.raises(ValueError, match="bad"):
        slots_commands._run_slot_verb(ARGS, "k", _raise(ValueError("bad")))
