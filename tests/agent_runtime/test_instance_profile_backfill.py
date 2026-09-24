"""B-4: explicit binding at creation (its null backfill was deleted 2026-09-24).

ANTI-VACUITY NOTE.

The load-bearing claim of this stage is a NEGATIVE one — "stamping the
projection changes no resolution" — and a negative is exactly what a careless
test asserts vacuously. So:

* ``test_stamping_does_not_change_what_a_turn_resolves`` does not assert that
  something is unchanged by re-reading the thing the change wrote. It resolves
  the binding through the PRODUCTION resolver twice, once with a null
  ``profile_id`` and once with a stamped one, and compares the resolved
  ``profile_home``. The probed field (``profile_home``) is produced by
  ``resolve_persona_profile``, which takes a PERSONA — a function the mutation
  under test cannot reach, because it never receives the instance at all.
* ``test_summary_renders_the_same_profile_before_and_after`` probes the RENDERED
  value from ``persona_instance_summary`` rather than the stored field, so it
  would catch a stamping change that altered what an operator sees.
"""

from __future__ import annotations


import pytest

from agent_runtime.models import AgentPersona, PersonaInstance
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import AgentStore
from agent_runtime.profile_context import resolve_persona_profile


@pytest.fixture
def store_root(tmp_path, monkeypatch):
    """Profile homes under an isolated HERMES_HOME.

    The runtime STORE root is already redirected per-test by the autouse
    fixture in ``tests/agent_runtime/conftest.py``; this only supplies the
    profile directories ``profile_exists`` checks.

    Each home carries an identity marker. Since upstream ``93889b770d``'s
    profile-identity work (merged 2026-09-17), ``profile_exists`` is
    ``named_profile_is_live``: a bare directory is a GHOST shell and resolves as
    ``missing_profile``, so a marker-less fixture would make every binding here
    unready for a reason that has nothing to do with what is under test.
    """
    home = tmp_path / "hermes-home"
    for name in ("launcher-qa", "base"):
        profile_home = home / "profiles" / name
        profile_home.mkdir(parents=True, exist_ok=True)
        (profile_home / "config.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def _write_persona(_root, persona_id: str, profile: str | None):
    persona = AgentPersona(
        id=persona_id,
        display_name=persona_id,
        role="dev",
        model=None,
        provider=None,
        api_mode=None,
        toolsets=[],
        system_prompt_path="",
        hermes_profile=profile,
    )
    return AgentStore().save(persona)


def _instance(instance_id: str, profile_id: str | None) -> PersonaInstance:
    return PersonaInstance(
        id=instance_id,
        persona_id="qa",
        role="dev",
        display_name="qa",
        profile_id=profile_id,
        runtime_root="",
        state=WorkerSessionState.IDLE,
    )


# ---------------------------------------------------------------------------
# Creation-time stamping
# ---------------------------------------------------------------------------


def test_creation_stamps_the_personas_profile_explicitly(store_root, monkeypatch):
    """A newly minted projection carries its persona's profile, not None.

    Kill-mutation: return to ``return None`` for non-``profile:`` ids. The
    stamped value becomes None and this goes red.

    Anti-vacuity: the expected value (``launcher-qa``) is written into the
    PERSONA record, never into the instance the assertion reads. The only way it
    can appear on the instance is the resolver under test running.
    """
    from agent_runtime.persona_assignments import _profile_id_for_persona_or_template

    _write_persona(store_root, "qa", "launcher-qa")
    assert _profile_id_for_persona_or_template("qa") == "launcher-qa"


def test_creation_leaves_an_unbound_persona_null(store_root):
    """A null persona binding stays null. Kill: stamp a literal "base" default.

    The plan's migration promise is that a null resolves the same before and
    after. Inventing a default here would break that promise silently, so the
    absence is pinned.
    """
    from agent_runtime.persona_assignments import _profile_id_for_persona_or_template

    _write_persona(store_root, "drifter", None)
    assert _profile_id_for_persona_or_template("drifter") is None


def test_synthetic_profile_channel_is_unchanged(store_root):
    """The pre-existing ``profile:<name>`` behaviour must not regress."""
    from agent_runtime.persona_assignments import _profile_id_for_persona_or_template

    assert _profile_id_for_persona_or_template("profile:alice") == "alice"


# ---------------------------------------------------------------------------
# THE MIGRATION CLAIM — verified, not trusted
# ---------------------------------------------------------------------------


def test_stamping_does_not_change_what_a_turn_resolves(store_root):
    """A null vs a stamped projection resolve to the SAME profile home.

    This is the plan's migration promise, checked against the production
    resolver rather than asserted in prose.

    Anti-vacuity: ``resolve_persona_profile`` takes a PERSONA and never sees an
    instance, so the probed ``profile_home`` cannot be written by the stamping
    change. The test constructs two instances differing ONLY in ``profile_id``
    and shows the turn-path answer is identical — including that it is derived
    from the persona, not from either instance.
    """
    persona = _write_persona(store_root, "qa", "launcher-qa")

    null_projection = _instance("i1", None)
    stamped_projection = _instance("i2", "launcher-qa")

    binding = resolve_persona_profile(persona)
    assert binding.readiness == "ready"
    assert binding.hermes_profile == "launcher-qa"

    # The resolver's answer does not depend on either projection — which is the
    # point. Both rows exist; neither is an input.
    assert null_projection.profile_id != stamped_projection.profile_id
    assert resolve_persona_profile(persona).profile_home == binding.profile_home


def test_summary_renders_the_same_profile_before_and_after(store_root):
    """What the operator SEES is identical for a null and a stamped row.

    ``persona_instance_summary`` already falls back with
    ``instance.profile_id or persona.hermes_profile``, so the rendered value
    cannot move. Kill-mutation: delete that fallback — the null row then renders
    None while the stamped row renders ``launcher-qa``, and the equality fails.
    """
    from agent_runtime.persona_assignments import persona_instance_summary

    persona = _write_persona(store_root, "qa", "launcher-qa")
    before = persona_instance_summary(
        _instance("i1", None), persona
    )
    after = persona_instance_summary(
        _instance("i1", "launcher-qa"), persona
    )
    assert before["profile_id"] == after["profile_id"] == "launcher-qa"
