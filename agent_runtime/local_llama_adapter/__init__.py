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
# 2026-09-25) is no longer read (owner 2026-09-29): stored rows carrying it are rewritten
# once at startup (``legacy_id_migration``, run from the eternia-harness plugin).
PROVIDER_ID_ALIASES = frozenset({PROVIDER_ID})
# "Hermes" alone names upstream (owner naming ruling 2026-09-29); this is the fork's.
DISPLAY_NAME = "Eternia Harness local llama"
# The ``requested_provider`` a managed local turn is built with. The two sub-64K floor
# exemption seams (``agent/agent_init.py``, ``agent/conversation_compression.py``) read this
# name, never a copy of its value; it is a turn marker, never a provider id a client sees.
FLOOR_EXEMPTION_REQUESTED_PROVIDER = "local-llama-hermes"
SCHEMA = "hermes.local_llama/v1"
SETUP_SCHEMA = "hermes.local_llama.setup/v1"
MODEL_ALIAS_PREFIX = "hermes-local-"


def is_local_llama_provider(provider) -> bool:
    """The one chokepoint for "is this persona on the managed local model": ``PROVIDER_ID``
    (``llamacpp``) only."""
    return provider in PROVIDER_ID_ALIASES


def model_alias(model_id: str) -> str:
    return MODEL_ALIAS_PREFIX + model_id
