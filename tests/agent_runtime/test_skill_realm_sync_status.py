"""The per-realm sync status a shared skill's catalog row carries.

``prompt_observability.skills_context._skill_realm_sync`` is what ``_skill_row``
attaches as ``realm_sync`` for every skill resolved from the shared root. The reach
census found it live and untested (dead-code queue, second instalment); this pins
its status ladder, one realm per rung.
"""

from __future__ import annotations

from agent_runtime.prompt_observability.skills_context import _skill_realm_sync


def _realm(realm_id: str, **fields) -> dict:
    return {"realm_id": realm_id, "name": realm_id.title(), **fields}


def test_each_realm_reports_where_the_skill_stands_in_it():
    realms = [
        _realm("r-all", skill_publish_mode="all", sync_state="in_sync"),
        _realm("r-picked", skill_publish_mode="selected", skill_selection=["alpha"], sync_state="in_sync"),
        _realm("r-left-out", skill_publish_mode="selected", skill_selection=["beta"], sync_state="in_sync"),
        _realm("r-drift", skill_publish_mode="all", sync_state="in_sync", skills_drift=["alpha"]),
        _realm("r-never-synced", skill_publish_mode="all"),
        _realm("r-behind", skill_publish_mode="all", sync_state="behind"),
        _realm("r-default-mode", sync_state="in_sync"),
    ]

    rows = _skill_realm_sync("alpha", realms)

    assert [(row["realm_id"], row["status"]) for row in rows] == [
        ("r-all", "in_sync"),
        ("r-picked", "in_sync"),
        ("r-left-out", "not_published"),
        ("r-drift", "drifted"),
        ("r-never-synced", "unknown"),
        ("r-behind", "unknown"),
        ("r-default-mode", "in_sync"),
    ]
    assert rows[0]["name"] == "R-All"


def test_a_skill_left_out_of_a_realm_is_not_published_even_when_it_drifted_there():
    """Publication is decided first: drift in a realm that does not carry the skill is moot."""
    realms = [_realm("r", skill_publish_mode="selected", skill_selection=[], skills_drift=["alpha"],
                     sync_state="in_sync")]
    assert _skill_realm_sync("alpha", realms)[0]["status"] == "not_published"
    # Positive control: the same realm selecting the skill reports the drift.
    realms[0]["skill_selection"] = ["alpha"]
    assert _skill_realm_sync("alpha", realms)[0]["status"] == "drifted"
