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

PROVIDER_ID = "local-llama-hermes"
DISPLAY_NAME = "Local llama Hermes"
SCHEMA = "hermes.local_llama/v1"
SETUP_SCHEMA = "hermes.local_llama.setup/v1"
MODEL_ALIAS_PREFIX = "hermes-local-"


def model_alias(model_id: str) -> str:
    return MODEL_ALIAS_PREFIX + model_id
