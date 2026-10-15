"""``NativeContext.roster`` loads the runtime config once per walk, not per instance."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import agent_runtime.config as config_mod
import agent_runtime.persona_assignments as assignments_mod
import agent_runtime.persona_lifecycle as lifecycle_mod
import agent_runtime.profile_context as profile_mod
import agent_runtime.workspace_scope as scope_mod
from agent_runtime.discussions.native_context import NativeContext


def _context() -> NativeContext:
    ctx = object.__new__(NativeContext)
    ctx.install_id = "install-1"
    ctx.scope = lambda: nullcontext()
    ctx.workspace = lambda workspace_id: None
    return ctx


def _walk(monkeypatch, count: int) -> tuple[list[dict], list[int]]:
    instances = [
        SimpleNamespace(id=f"inst-{i}", persona_id="p", display_name=f"Agent {i}", profile_id=None)
        for i in range(count)
    ]
    by_id = {inst.id: inst for inst in instances}

    class _Store:
        def scan_all(self):
            return SimpleNamespace(unreadable=0, instances=instances)

        def get(self, instance_id):
            return by_id[instance_id]

        def retired_instance_archive_path(self, *_args, **_kwargs):
            return None

    loads: list[int] = []
    monkeypatch.setattr(assignments_mod, "PersonaInstanceStore", _Store)
    monkeypatch.setattr(config_mod, "load_agent_runtime_config", lambda: loads.append(1) or object())
    monkeypatch.setattr(config_mod, "ensure_persisted_personas", lambda _cfg: [SimpleNamespace(id="p")])
    monkeypatch.setattr(lifecycle_mod, "is_runtime_persona", lambda _p: True)
    monkeypatch.setattr(profile_mod, "resolve_persona_profile",
                        lambda _p: SimpleNamespace(readiness="ready", hermes_profile="default"))
    monkeypatch.setattr(scope_mod, "effective_workspace_id", lambda _i, active_workspace_id: active_workspace_id)
    return _context().roster("ws"), loads


def test_the_roster_loads_the_runtime_config_once_for_every_instance(monkeypatch):
    rows, loads = _walk(monkeypatch, 4)
    assert [row["available"] for row in rows] == [True] * 4
    assert len(loads) == 1


def test_a_single_resolve_still_loads_its_own_config(monkeypatch):
    """Positive control: the per-member door (``resolve`` without ``personas``) loads."""

    from agent_runtime.discussions.definitions import ParticipantRef

    _rows, loads = _walk(monkeypatch, 1)
    loads.clear()
    row = _context().resolve(ParticipantRef("install-1", "inst-0"), "ws")
    assert row["persona_id"] == "p"
    assert len(loads) == 1
