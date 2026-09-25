"""Thin ACP binding for read-only skill inspection and persisted load evidence."""
import asyncio
import json
from contextlib import contextmanager

from acp import RequestError

from agent.runtime_cwd import reset_session_cwd, set_session_cwd
from agent_runtime.skill_activity import skill_load_history
from agent_runtime.skill_inspection import SkillInspectionError, SkillInspectionReason

SKILLS_CAPABILITY = {"version": 1, "list": True, "detail": True, "loadActivity": True}


@contextmanager
def skill_inspection_scope(cwd):
    token = set_session_cwd(cwd)
    try:
        yield
    finally:
        reset_session_cwd(token)


def _can_load(state) -> bool:
    return any(tool.get("function", {}).get("name") == "skill_view"
               for tool in getattr(state.agent, "tools", ()) or ())


def _list(manager, state, params):
    from tools.skills_tool import skill_inspection_reader
    return {"skills": skill_inspection_reader().catalog(can_load=_can_load(state))}


def _detail(manager, state, params):
    from tools.skills_tool import skill_inspection_reader
    identifier = params.get("skillId")
    if not isinstance(identifier, str) or not identifier or len(identifier) > 512:
        raise RequestError.invalid_params()
    return {"skill": skill_inspection_reader().detail(identifier, can_load=_can_load(state))}


def _history(manager, state, params):
    messages, complete = manager.skill_history(state.session_id)
    return {"loaded": skill_load_history(messages), "historyComplete": complete}


_READS = {"hermes/skills/list": _list, "hermes/skills/detail": _detail,
          "hermes/skills/history": _history}


class SkillsInspectionMixin:
    async def ext_method(self, method, params):
        read = _READS.get(method)
        if read is None:
            raise RequestError.method_not_found(method)
        session_id = params.get("sessionId")
        if not isinstance(session_id, str):
            raise RequestError.invalid_params()
        state = self.session_manager.peek_session(session_id)
        if state is None:
            raise RequestError.resource_not_found()
        cwd = state.cwd

        def inspect():
            try:
                with skill_inspection_scope(cwd):
                    result = {"version": 1, "sessionId": session_id,
                              **read(self.session_manager, state, params)}
                    if len(json.dumps(result, ensure_ascii=True)) > 1024 * 1024 - 1024:
                        raise SkillInspectionError(SkillInspectionReason.RESPONSE_TOO_LARGE)
                    return result
            except SkillInspectionError as error:
                raise RequestError(-32010, "Skill is unavailable", {"reason": error.reason}) from error
            except OSError as error:
                raise RequestError(-32010, "Skill could not be read", {"reason": "read_failed"}) from error

        result = await asyncio.to_thread(inspect)
        if self.session_manager.peek_session(session_id) is not state or state.cwd != cwd:
            raise RequestError.resource_not_found()
        return result
