"""The prompt-observability package: what the model was sent, what it cost, and where a reader finds it.

Owner doc: ``docs/agent-runtime-harness/07-observability.md``. This file re-exports
the names production importers take (``snapshot``, the chat turn commit, the
harness CLI); import anything else from the module that owns it, and patch a
name in the module that LOOKS IT UP.

Entry points (lanes): ``mission_chat`` (the chat turn's row), ``turn_results``
(what the finished turn adds; the slim final-frame copy), ``snapshot_frame`` (the
snapshot's section).

Modules, by layer (lowest first; a module imports only its own layer or lower):

* policy — ``spans`` (the row's thread-local sub-span timings), ``hoist`` (the S3
  read model: hoisted skill refs, evicted debug stubs), ``context_budget`` (the
  context-window budget and its bases), ``context_files`` (the profile's context
  files and their prompt contribution), ``safe_views`` (bounded, redacted views
  of the model input and usage).
* stores — ``workspace_agents`` (the workspace ``AGENTS.md`` read),
  ``catalog_store`` (the content-addressed skills catalogs), ``context_store``
  (the persisted per-lane rows, their index and retention — one writer),
  ``catalog_lookup`` (a hoisted ref resolved against both stores),
  ``skills_resolver`` (which skills a persona reaches; the installed-catalog
  memo), ``skills_context`` (the available and used skill rows).
* lanes — ``mission_chat``, ``turn_results``, ``snapshot_frame``.

Stores written: ``paths.prompt_observability_dir`` / ``_index_path`` /
``_archive_dir`` (``context_store``), ``paths.prompt_observability_catalogs_dir``
(``catalog_store``). Never imported from here: ``hermes_cli.harness``, and no
module here imports a layer above its own (W0-G6).
"""

from __future__ import annotations

from .catalog_lookup import skills_catalog_by_hash
from .context_store import load_persisted_context_row, persist_prompt_observability_context
from .mission_chat import mission_chat_prompt_observability
from .safe_views import turn_usage_from_result
from .skills_resolver import _SkillObservabilityResolver
from .snapshot_frame import snapshot_prompt_observability
from .spans import PROMPT_OBSERVABILITY_TIMINGS_KEY
from .turn_results import attach_prompt_observability_turn_results, slim_chat_final_observability
from .workspace_agents import load_workspace_agents_context

__layer__ = "lanes"
__all__ = [
    "PROMPT_OBSERVABILITY_TIMINGS_KEY",
    "_SkillObservabilityResolver",
    "attach_prompt_observability_turn_results",
    "load_persisted_context_row",
    "load_workspace_agents_context",
    "mission_chat_prompt_observability",
    "persist_prompt_observability_context",
    "skills_catalog_by_hash",
    "slim_chat_final_observability",
    "snapshot_prompt_observability",
    "turn_usage_from_result",
]
