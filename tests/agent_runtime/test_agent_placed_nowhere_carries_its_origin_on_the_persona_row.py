"""An agent placed nowhere still tells Eternia it ships with Eternia, or what it is based on.

RT-FU-AN-AGENT-PLACED-NOWHERE-TELLS-ETERNIA-IT-SHIPS-WITH-ETERNIA-OR-WHAT-IT-IS-BASED-ON (review w1122b.1).
``runtime.agent.directory`` lists placed instances only, so the persona row (``snapshot/summaries.py::
_agent_summary``, the one builder of the snapshot's agents section and the persona state patch) is the only
row an agent with no instance reaches Eternia on. It now spreads ``directory_fields(agent)``, the one owner of
``origin`` / ``based_on`` / ``agent_name`` / ``locally_changed``, so no second list is kept.
"""

from __future__ import annotations

from dataclasses import replace

from agent_runtime.bundled_agents import catalog
from agent_runtime.bundled_agents.resolve import reference_record
from agent_runtime.models import AgentPersona
from agent_runtime.snapshot.summaries import _agent_summary

NEKO = "neko_supervisor"


def test_a_shipped_agent_placed_nowhere_carries_its_eternia_mark():
    """KILLING MUTATION (run 2026-11-22): the ``**directory_fields(agent)`` line dropped from ``_agent_summary``
    -> KeyError 'origin' (red); restored -> green."""

    row = _agent_summary(reference_record(catalog.shipped_agent(NEKO)))

    assert row["origin"] == "eternia"
    assert row["locally_changed"] is False
    assert "based_on" not in row


def test_a_named_copy_placed_nowhere_carries_what_it_is_based_on():
    """KILLING MUTATION (run 2026-11-22): the same line dropped -> KeyError 'based_on' (red); restored -> green."""

    copy = replace(
        reference_record(catalog.shipped_agent(NEKO)),
        id="my_neko", display_name="My Neko", origin=None, based_on={"id": NEKO, "name": "Neko"},
    )

    row = _agent_summary(copy)

    assert row["based_on"] == {"id": NEKO, "name": "Neko"}
    assert row["agent_name"] == "My Neko"
    assert "origin" not in row


def test_an_agent_of_the_users_own_carries_neither_mark():
    row = _agent_summary(AgentPersona("mine", "Mine", "helper", None, None, None))

    assert "origin" not in row and "based_on" not in row
