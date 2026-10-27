"""The course persona tools (RT-COURSE-PERSONA-TOOLS; plan ``course-turn-credential-2026-10-25.md`` §2.4).

Real git against a LOCAL bare remote (``test_course_authoring``'s fixture), the turn's credential held by the
real ``turn_secrets`` and the persona read from the real turn binding (``persona_turn_binding`` +
``live_turns``); only the instance store's ``get`` is a stand-in.
"""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from agent_runtime import course_tool, turn_secrets
from tests.agent_runtime.test_course_authoring import COURSE, GITHUB_URL, SECRET, FakeGitHub, _credential, _url
from tests.agent_runtime.test_course_authoring import remote  # noqa: F401 — the bare-remote fixture

TURN = "turn_course_1"


@pytest.fixture
def persona(monkeypatch):
    """The persona instance ``inst_ada`` resolves to persona ``p_ada`` (display name ``Ada``)."""

    from agent_runtime import persona_assignments

    class Instances:
        def get(self, instance_id):
            assert instance_id == "inst_ada"
            return SimpleNamespace(persona_id="p_ada", display_name="Ada")

    monkeypatch.setattr(persona_assignments, "PersonaInstanceStore", Instances)


@contextmanager
def _turn(secrets: dict | None):
    from agent_runtime.live_turns import live_turn
    from agent_runtime.persona_turn_binding import bind_persona_turn_agent

    agent = SimpleNamespace()
    turn_secrets.put(TURN, secrets or {})
    try:
        with turn_secrets.bound(TURN), live_turn(turn_id=TURN, session_id="s1", persona_instance_id="inst_ada",
                                                 agent=agent), bind_persona_turn_agent(agent):
            yield
    finally:
        turn_secrets.drop(TURN)


def _call(handler, args) -> dict:
    return json.loads(handler(args))


def test_every_tool_refuses_course_credential_missing_without_a_turn_credential(remote, persona):  # noqa: F811
    """Killing mutation: deleting ``_turn_credential``'s None check turns the refusal into an AttributeError."""

    calls = [(course_tool.handle_course_checkout, {"course_public_id": COURSE}),
             (course_tool.handle_course_commit, {"course_public_id": COURSE, "branch": "intro", "message": "m",
                                                 "files": {"a.md": "a"}}),
             (course_tool.handle_course_pull_request, {"course_public_id": COURSE, "branch": "intro", "title": "t"})]
    with _turn(None):
        for handler, args in calls:
            assert _call(handler, args)["error"] == course_tool.REASON_CREDENTIAL_MISSING
            assert _call(handler, {**args, "credential": _credential(_url(remote))})["error"] == (
                course_tool.REASON_CREDENTIAL_MISSING)
    # Positive control: the same checkout in a turn holding the credential runs.
    with _turn({"course_credential": _credential(_url(remote))}):
        assert _call(course_tool.handle_course_checkout, {"course_public_id": COURSE})["outcome"] == "added_fetched"
    # And once the turn's secrets are dropped, the same bound turn reads none.
    with turn_secrets.bound(TURN):
        assert _call(course_tool.handle_course_checkout, {"course_public_id": COURSE})["error"] == (
            course_tool.REASON_CREDENTIAL_MISSING)


def test_a_credential_for_another_course_refuses_subject_mismatch(remote, persona):  # noqa: F811
    with _turn({"course_credential": _credential(_url(remote))}):
        answer = _call(course_tool.handle_course_checkout, {"course_public_id": "crs_other"})
    assert answer["error"] == "credential_subject_mismatch"


def test_a_commit_is_authored_by_the_turns_persona_on_its_branch_and_never_echoes_the_secret(remote, persona):  # noqa: F811
    """Killing mutation: ``_calling_persona`` answering a fixed ``agent`` id lands ``agent/agent/intro``."""

    with _turn({"course_credential": _credential(_url(remote))}):
        _call(course_tool.handle_course_checkout, {"course_public_id": COURSE})
        answer = course_tool.handle_course_commit({"course_public_id": COURSE, "branch": "intro",
                                                   "message": "Add the intro", "files": {"lessons/00.md": "zero\n"}})
    receipt = json.loads(answer)
    assert receipt["branch"] == "agent/p_ada/intro" and receipt["files"] == ["lessons/00.md"]
    assert SECRET not in answer
    author = subprocess.run(["git", "log", "-1", "--format=%an <%ae>", "agent/p_ada/intro"], cwd=remote,
                            capture_output=True, text=True, check=True).stdout.strip()
    assert author == "Ada <p_ada@eternia.agents>"


def test_a_pull_request_rides_the_turns_credential_and_persona(monkeypatch, persona):
    from agent_runtime import course_authoring

    github = FakeGitHub()
    monkeypatch.setattr(course_authoring, "_github_request", lambda: github)
    monkeypatch.setattr(course_authoring, "_origin_head", lambda _git, _repo: "main")
    (course_authoring.paths.course_checkout_dir(COURSE) / ".git").mkdir(parents=True, exist_ok=True)
    with _turn({"course_credential": _credential(GITHUB_URL)}):
        answer = course_tool.handle_course_pull_request({"course_public_id": COURSE, "branch": "intro",
                                                         "title": "Add the intro"})
    assert json.loads(answer)["branch"] == "agent/p_ada/intro" and json.loads(answer)["number"] == 7
    assert {call[2] for call in github.calls} == {SECRET} and SECRET not in answer


def test_a_call_outside_a_persona_turn_refuses_persona_unknown(remote):  # noqa: F811
    turn_secrets.put(TURN, {"course_credential": _credential(_url(remote))})
    try:
        with turn_secrets.bound(TURN):
            answer = _call(course_tool.handle_course_commit, {"course_public_id": COURSE, "branch": "intro",
                                                              "message": "m", "files": {"a.md": "a"}})
    finally:
        turn_secrets.drop(TURN)
    assert answer["error"] == course_tool.REASON_PERSONA_UNKNOWN


def test_the_course_toolset_is_a_builtin_harness_core_includes():
    """Killing mutation: ``course`` left out of ``HARNESS_CORE_INCLUDES`` hides the tools from a persona."""

    from agent_runtime.harness_toolset import HARNESS_CORE_INCLUDES
    from agent_runtime.toolset_names import expand_toolset_names, unknown_toolset_names
    from tools.toolset_manifest import builtin_toolset_names

    assert course_tool.COURSE_TOOLSET in HARNESS_CORE_INCLUDES
    assert course_tool.COURSE_TOOLSET in expand_toolset_names(["harness_core"])
    # Known from the committed manifest, so a declaration read never discovers plugins to know it.
    assert course_tool.COURSE_TOOLSET in builtin_toolset_names()
    assert unknown_toolset_names([course_tool.COURSE_TOOLSET]) == ()
    assert unknown_toolset_names(["course_not_a_toolset"]) == ("course_not_a_toolset",), "positive control"


def test_a_harness_core_profile_reaches_the_course_tools(bundled_persona_profiles):
    import textwrap

    import model_tools
    from agent_runtime.models import AgentPersona
    from agent_runtime.parse_cache import clear_parse_cache
    from agent_runtime.persona_profiles import effective_toolsets
    from hermes_cli.profiles import get_profile_dir

    home = get_profile_dir("course-probe")
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(textwrap.dedent("toolsets:\n  - harness_core\n"), encoding="utf-8")
    clear_parse_cache()
    persona = AgentPersona(id="course-probe", display_name="Course probe", role="dev", model=None, provider=None,
                           api_mode="codex_responses", system_prompt_path="", hermes_profile="course-probe")
    definitions = model_tools.get_tool_definitions(enabled_toolsets=effective_toolsets(persona),
                                                   quiet_mode=True, skip_tool_search_assembly=True)
    names = {definition["function"]["name"] for definition in definitions}
    assert {"course_checkout", "course_commit", "course_pull_request"} <= names
    assert "terminal" in names, "positive control: the profile resolved harness_core"
