"""The launcher's ``runtime.local_llama.*`` contract, served over upstream's managed runtime.

Upstream ``hermes_cli.local_runtime`` owns the engine: install (``binaries``), spawn and
restart (``supervisor``/``processes``), GGUF headers (``gguf``), hardware (``hardware``) and
the ``llamacpp`` endpoint (``endpoint``). This package keeps only what upstream has no
equivalent for and the owner ruled KEEP (2026-09-24): guarded idempotent receipts, the
whole-turn lease, the log cursor, the visibility block, per-model load knobs and generation
parameters, and the two gap fallbacks (a user-supplied ``llama-server``, extra model roots).
No import-time process or filesystem I/O.
"""

__layer__ = "policy"

PROVIDER_ID = "llamacpp"
# The id this provider published before it took upstream's ``llamacpp`` (owner ruling
# 2026-09-25). Still read on input — a launcher build that sends it, a persona row stored
# with it — and never written. It leaves ``PROVIDER_ID_ALIASES`` in the step after the
# launcher's l9 lane lands (it already reads ``llamacpp`` and folds this id at its parse
# boundary), together with a rewrite-and-report of stored rows that still carry it.
LEGACY_PROVIDER_ID = "local-llama-hermes"
PROVIDER_ID_ALIASES = frozenset({PROVIDER_ID, LEGACY_PROVIDER_ID})
# "Hermes" alone names upstream (owner naming ruling 2026-09-29); this is the fork's.
DISPLAY_NAME = "Eternia Harness local llama"
# The ``requested_provider`` a managed local turn is built with. Two fork seams inside upstream
# files (``agent/agent_init.py``, ``agent/conversation_compression.py``: the sub-64K floor
# exemptions) compare against this literal, so it stays the old spelling until a seam lane
# moves those two lines; it is a turn marker, never a provider id a client sees.
FLOOR_EXEMPTION_REQUESTED_PROVIDER = "local-llama-hermes"
SCHEMA = "hermes.local_llama/v1"
SETUP_SCHEMA = "hermes.local_llama.setup/v1"
MODEL_ALIAS_PREFIX = "hermes-local-"


def is_local_llama_provider(provider) -> bool:
    """The one chokepoint for "is this persona on the managed local model". Readers accept
    every id in ``PROVIDER_ID_ALIASES``; writers normalize to ``PROVIDER_ID`` (``llamacpp``)."""
    return provider in PROVIDER_ID_ALIASES


def model_alias(model_id: str) -> str:
    return MODEL_ALIAS_PREFIX + model_id
