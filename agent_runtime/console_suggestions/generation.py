"""Free-form next-message generation via the manager-owned plugin LLM facade.

Context clipping and cleanup adapted from next-prompt 0.3.1, revision
c200200d6678dc6b093bab03c2e00a4f5a5043ed. See THIRD_PARTY_LICENSES/next-prompt.txt.
"""
from __future__ import annotations

from threading import RLock

from functools import partial
from agent_runtime.suggestions import generation as suggestions
from hermes_constants import get_hermes_home
from .settings import TASK, SuggestionRefused

__layer__ = "lanes"
_contexts = {}
_context_lock = RLock()


def register_suggestion_task(ctx) -> None:
    ctx.register_auxiliary_task(TASK, display_name="Agent Console follow-up suggestions",
        description="Optional contextual drafts in Eternia Agent Console; off by default.")
    key = str(get_hermes_home().resolve())
    with _context_lock:
        _contexts[key] = ctx

    def unload():
        with _context_lock:
            if _contexts.get(key) is ctx:
                _contexts.pop(key)

    ctx.on_unload(unload)


def generate_suggestion(messages: list[dict]) -> dict:
    from hermes_cli.plugins import get_plugin_manager

    manager = get_plugin_manager()
    manager.discover_and_load()
    with _context_lock:
        ctx = _contexts.get(str(get_hermes_home().resolve()))
    if ctx is None:
        raise SuggestionRefused("plugin_unavailable")
    return suggestions.generate_suggestion(messages, partial(ctx.llm.complete,
        task=TASK, purpose="console_follow_up"))
