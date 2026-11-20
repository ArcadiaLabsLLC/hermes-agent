"""Adding an instance with no placement id mints one, at both ``--add-instance`` doors.

The shared refusal (``agent_runtime.models.placement_id_not_discriminable_message``) tells
every placement door's caller to "omit --placement-id to have one minted". ``agent create``
did; ``persona instance create --add-instance`` and ``persona instance open-chat
--add-instance`` refused a missing id instead, so the two refusals contradicted each other
(RT-FU-ADD-INSTANCE-CLI-REFUSALS-CONTRADICT-EACH-OTHER, review w1118a.57 D13). Both doors now
mint with ``agent_create.mint_placement_id``. Driven through the real argparse tree.
"""

from __future__ import annotations

from agent_runtime.models import looks_like_deliberate_placement
from tests.hermes_cli.test_placement_id_discriminability import (  # the module's fixtures
    _instance_create,
    _instance_open,
    hermetic_runtime_root,
    qa_persona,
)


def _minted(data: dict) -> str:
    instance_id = data["persona_instance_id"]
    assert instance_id.startswith("personainst_qa_agent_"), data
    placement = instance_id.removeprefix("personainst_")
    assert looks_like_deliberate_placement(placement), placement
    return placement


def test_instance_create_mints_the_placement_id_it_was_not_given(qa_persona, capsys):
    code, data = _instance_create(capsys)
    assert code == 0, data
    assert data["placement_id"] == _minted(data)


def test_open_chat_add_instance_mints_the_placement_id_it_was_not_given(qa_persona, capsys):
    code, data = _instance_open(capsys)
    assert code == 0, data
    assert data["placement_id"] == _minted(data)


def test_two_unkeyed_adds_are_two_instances(qa_persona, capsys):
    first = _minted(_instance_create(capsys)[1])
    second = _minted(_instance_create(capsys)[1])
    assert first != second


def test_a_retried_add_with_the_same_message_id_converges_on_one_instance(qa_persona, capsys):
    first = _minted(_instance_create(capsys, "--client-message-id", "cmid-hwin-1")[1])
    again = _minted(_instance_create(capsys, "--client-message-id", "cmid-hwin-1")[1])
    other = _minted(_instance_create(capsys, "--client-message-id", "cmid-hwin-2")[1])
    assert first == again != other
