import builtins


def _block_environment_helper_import(monkeypatch):
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if (
            name == "agent.skill_utils"
            and "skill_matches_environment" in tuple(fromlist or ())
        ):
            raise ImportError(
                "cannot import name 'skill_matches_environment' from 'agent.skill_utils'"
            )
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


# test_prompt_builder_import_survives_missing_environment_helper was deleted
# (lane h10-fhrest, 2026-09-29): upstream's agent/prompt_builder.py now imports
# skill_matches_environment unconditionally, so the fallback it pinned no longer
# exists; the skills_tool half below is upstream's own delegate and still holds.


def test_skills_tool_environment_helper_fails_closed_for_tagged_skills(monkeypatch):
    from tools import skills_tool

    _block_environment_helper_import(monkeypatch)

    assert skills_tool.skill_matches_environment({}) is True
    assert skills_tool.skill_matches_environment({"environments": ["kanban"]}) is False
