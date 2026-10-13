"""H10: the targeted test boundary preserves its caller, including on failure."""

from contextvars import Context, ContextVar
from types import SimpleNamespace

import pytest

from tests._downstream.agent_conftest import _compression_rotation_context


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_rotation_boundary_preserves_caller_context(monkeypatch, bound, fails):
    from gateway import session_context
    from gateway.session_context import clear_session_vars, get_session_env, set_session_vars

    inherited = ContextVar("rotation_test_fixture", default="unset")
    monkeypatch.setenv("HERMES_SESSION_SOURCE", "override-src")
    monkeypatch.setattr(session_context, "_session_context_engaged", False)

    def exercise():
        inherited.set("fixture")
        if bound:
            set_session_vars(session_id="outer", source="outer-source")
        before = get_session_env("HERMES_SESSION_SOURCE")

        def scenario(*, value):
            assert inherited.get() == "fixture"
            inherited.set("changed")
            tokens = set_session_vars(session_id="inner", source="inner-source")
            try:
                assert get_session_env("HERMES_SESSION_SOURCE") == "inner-source"
                if fails:
                    raise AssertionError("scenario failed")
                return value
            finally:
                clear_session_vars(tokens)

        node = SimpleNamespace(
            nodeid="tests/agent/test_compression_worker_isolation.py::"
            "test_f5_session_contextvar_rebound_after_rotation",
            obj=scenario,
        )
        _compression_rotation_context.__wrapped__(SimpleNamespace(node=node), monkeypatch)
        if fails:
            with pytest.raises(AssertionError, match="scenario failed"):
                node.obj(value="result")
        else:
            assert node.obj(value="result") == "result"
        assert inherited.get() == "fixture"
        assert get_session_env("HERMES_SESSION_SOURCE") == before
        assert before == ("outer-source" if bound else "override-src")

    Context().run(exercise)


def test_other_tests_keep_their_original_callable(monkeypatch):
    def scenario():
        return "unchanged"

    node = SimpleNamespace(nodeid="tests/agent/test_other.py::test_scenario", obj=scenario)
    _compression_rotation_context.__wrapped__(SimpleNamespace(node=node), monkeypatch)
    assert node.obj is scenario
