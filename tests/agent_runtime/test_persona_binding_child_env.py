"""B-2: a child spawned inside a persona turn carries the persona's binding.

ANTI-VACUITY NOTE.

The trap in this file's subject matter is asserting on a variable the fixture
itself set. ``persona_profile_context`` writes ``os.environ["HERMES_HOME"]``, so
a test that enters the context and then reads ``os.environ["HERMES_HOME"]``
proves only that the context did what the test just watched it do — it says
nothing about what a CHILD would receive.

Every case below therefore probes the dict handed to the child, built by the
production factory, and compares it against a home the test did NOT write into
``os.environ``:

* ``test_mcp_child_env_carries_the_bound_profile_home`` compares the child's
  ``HERMES_HOME`` against ``binding.profile_home`` while ``HOME`` in the same
  dict points somewhere ELSE (``<profile>/home``). Under the pre-fix code the
  key is simply absent, and under a "just copy os.environ" mutant the two would
  still differ — the assertion pins the relationship between two keys, not the
  presence of one.
* ``test_factory_resolves_at_call_time_not_import_time`` builds the env twice
  under two DIFFERENT context bindings within one process. A module-load-time
  snapshot yields the same answer twice; only a call-time resolver yields two.
  The test asserts the two differ, which no frozen implementation can satisfy.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_runtime.profile_context import (
    PersonaProfileBinding,
    persona_profile_context,
)


def _profile(tmp_path: Path, name: str, *, with_home: bool = True) -> Path:
    home = tmp_path / "profiles" / name
    home.mkdir(parents=True, exist_ok=True)
    if with_home:
        (home / "home").mkdir(exist_ok=True)
    return home


def _binding(home: Path) -> PersonaProfileBinding:
    return PersonaProfileBinding(
        persona_id=f"persona_{home.name}",
        hermes_profile=home.name,
        profile_home=home,
        readiness="ready",
        summary="profile exists",
    )


# ---------------------------------------------------------------------------
# The A-5 bypass: stdio MCP children
# ---------------------------------------------------------------------------


def test_mcp_child_env_carries_the_bound_profile_home(tmp_path):
    """The stdio MCP child is told the persona's home, not left to infer it.

    Kill-mutation: delete the ``_inject_child_hermes_home(env)`` call in
    ``_build_safe_env`` (i.e. restore the pre-fix allowlist). ``HERMES_HOME`` is
    then absent from the child env entirely.

    Anti-vacuity: the assertion pins ``HERMES_HOME`` to the profile ROOT while
    asserting the same dict's ``HOME`` is the profile's ``home/`` SUBDIRECTORY.
    Those are two different paths, and the pre-fix behaviour (inherit ``HOME``,
    drop ``HERMES_HOME``) is exactly what makes a child resolve
    ``<profile>/home/.hermes``. A mutant that reinstates the old allowlist
    cannot satisfy the pair; nor can one that blindly copies ``os.environ``,
    because ``HOME`` and ``HERMES_HOME`` must come out DIFFERENT.
    """
    from tools.mcp_tool_config import _build_safe_env

    home = _profile(tmp_path, "alice")
    with persona_profile_context(_binding(home), runtime_root=tmp_path / "rt"):
        child = _build_safe_env(None)

    assert child.get("HERMES_HOME") == str(home)
    # The two keys must NOT be the same path — that inequality is the whole bug.
    assert child.get("HOME") == str(home / "home")
    assert child["HERMES_HOME"] != child["HOME"]
    # And the child must not be handed a home derived from HOME.
    assert child["HERMES_HOME"] != str(Path(child["HOME"]) / ".hermes")


def test_mcp_child_env_never_leaks_the_head_auth_home(tmp_path):
    """HERMES_AUTH_HOME stays out of the child. Stated decision, pinned.

    Kill-mutation: add ``HERMES_AUTH_HOME`` to the injected keys. This goes red,
    which is the point — the head-pin is deliberate and forwarding it is a
    credential-resolution change owned by a different plan.
    """
    from tools.mcp_tool_config import _build_safe_env

    home = _profile(tmp_path, "alice")
    with persona_profile_context(_binding(home), runtime_root=tmp_path / "rt"):
        assert os.environ.get("HERMES_AUTH_HOME")  # the context DID set it
        child = _build_safe_env(None)
    assert "HERMES_AUTH_HOME" not in child


def test_server_config_env_block_still_overrides_the_injected_home(tmp_path):
    """Injection sits at layer 1, so a config ``env:`` block still wins.

    Kill-mutation: move the injection AFTER the ``user_env`` update. The
    operator's explicit config is then silently overwritten — a regression in
    the documented merge order.
    """
    from tools.mcp_tool_config import _build_safe_env

    home = _profile(tmp_path, "alice")
    override = str(tmp_path / "explicit")
    with persona_profile_context(_binding(home), runtime_root=tmp_path / "rt"):
        child = _build_safe_env({"HERMES_HOME": override})
    assert child["HERMES_HOME"] == override


def test_unbound_persona_child_still_gets_a_home(tmp_path):
    """A persona with no binding is not a reason to hand the child nothing.

    ``resolve_persona_profile`` maps a null ``hermes_profile`` to "inherit the
    active Harness profile", so the child should receive whatever the ambient
    resolution is — never an absent key.
    """
    from tools.mcp_tool_config import _build_safe_env

    unbound = PersonaProfileBinding(
        persona_id="p",
        hermes_profile=None,
        profile_home=None,
        readiness="ready",
        summary="inherits active Harness profile",
    )
    with persona_profile_context(unbound, runtime_root=tmp_path / "rt"):
        child = _build_safe_env(None)
    assert child.get("HERMES_HOME")


# ---------------------------------------------------------------------------
# Call-time vs import-time resolution in the shared env factories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory_name", ["hermes_subprocess_env", "build_subprocess_env"]
)
def test_factory_resolves_at_call_time_not_import_time(tmp_path, factory_name):
    """Two bindings in ONE process must yield two different child homes.

    Kill-mutation: snapshot ``os.environ`` (or the resolved home) at module
    import and build from the snapshot. Both calls then return the same value
    and the inequality assertion fails.

    Anti-vacuity: the probe is an INEQUALITY between two calls in the same
    interpreter, so it cannot be satisfied by any frozen value — including one
    the fixture itself happened to write. Neither expected path is ever placed
    in ``os.environ`` by this test directly; both arrive through
    ``persona_profile_context``.
    """
    from tools.environments import local as local_env

    factory = getattr(local_env, factory_name)
    alice = _profile(tmp_path, "alice")
    base = _profile(tmp_path, "base")

    with persona_profile_context(_binding(alice), runtime_root=tmp_path / "rt"):
        first = factory()["HERMES_HOME"]
    with persona_profile_context(_binding(base), runtime_root=tmp_path / "rt"):
        second = factory()["HERMES_HOME"]

    assert first != second, f"{factory_name} froze its home"
    assert Path(first).name == "alice"
    assert Path(second).name == "base"


def test_agent_chat_dispatch_child_states_the_home_rather_than_inheriting(tmp_path):
    """The one hermes-CLI child the runtime spawns names its home explicitly.

    ``build_dispatch_argv`` carries no ``--profile``; the home rides the env
    instead, and ``child_environment`` STATES it rather than letting the child
    re-derive one. Kill-mutation: drop the explicit ``HERMES_HOME`` assignment
    in ``child_environment`` — the child then falls back to whatever ambient
    resolution it lands on.

    Anti-vacuity: the expected value is the SENDER's resolved home, captured
    inside a persona context, and compared against a spec value this test set to
    a path that appears nowhere in ``os.environ``.
    """
    from tools.agent_chat_dispatch import child_environment

    stated = str(tmp_path / "profiles" / "alice")
    env = child_environment({"hermes_home": stated})
    assert env["HERMES_HOME"] == stated
