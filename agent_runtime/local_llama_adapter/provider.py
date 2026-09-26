"""Persona-facing half: the provider profile, the visibility block, and the turn route.

A persona that picked a local model keeps the launcher's provider id ``local-llama-hermes`` and
a preset UUID (the launcher contract). Upstream's ``llamacpp`` is accepted as an input alias of
that id (``is_local_llama_provider``) until the launcher switches; what is published stays
``local-llama-hermes``. The turn itself runs on upstream's ``llamacpp`` provider: the endpoint
comes from ``resolve_runtime_provider(requested="llamacpp")`` (the ``server.json`` upstream's
supervisor publishes), under a whole-turn lease (row 12). Row 10 (generation parameters) rides
the agent factory's kwargs; row 21 is the visibility block.

The read projection (``hermes_cli.config_read_scope``) pins ``model.context_length`` to the
window the router actually loaded and routes every auxiliary task to that same model. The two
sub-64K floor exemptions (``agent_init.py`` / ``conversation_compression.py``, owner-ruled
KEEP, "configurable floor PR, held") key on exactly that pin.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

from . import DISPLAY_NAME, PROVIDER_ID, is_local_llama_provider
from .config import ConfigStore


def provider_profile():
    from providers.base import ProviderProfile
    return ProviderProfile(name=PROVIDER_ID, display_name=DISPLAY_NAME, api_mode="chat_completions")


def catalog_visibility():
    from agent_runtime.config import harness_root_config_path
    config = ConfigStore(harness_root_config_path()).read()
    return {"schema": "hermes.local_llama.catalog/v1", "provider_id": PROVIDER_ID,
            "display_name": DISPLAY_NAME, "configured": bool(config.get("executable_path")),
            "models": [{"model_id": p["model_id"], "display_name": p["display_name"],
                        "context_length": p["load"]["context_size"],
                        "selectable": Path(p["gguf_path"]).is_file(),
                        "unavailable_reason": None if Path(p["gguf_path"]).is_file() else "missing_file"}
                       for p in config.get("presets", [])]}


def resolve(model_id, *, root=None):
    from .binding import get_manager
    return get_manager(root=root, create=False).runtime(model_id)


def project_config(config, runtime):
    parameters = runtime["local_parameters"]
    model = config.get("model")
    model = dict(model) if isinstance(model, dict) else {}
    model.update(provider=runtime["provider"], default=runtime["model"], base_url=runtime["base_url"],
                 context_length=parameters["effective_context_size"])
    config["model"] = model
    # Every auxiliary task inherits the managed model. No credential enters the projection;
    # scoped_runtime_main carries it in memory.
    auxiliary = config.setdefault("auxiliary", {})
    if not isinstance(auxiliary, dict):
        auxiliary = config["auxiliary"] = {}
    for key in set(auxiliary) | {"compression"}:
        if key == "compression" or isinstance(auxiliary.get(key), dict):
            auxiliary[key] = {"provider": "main", "model": runtime["model"], "fallback_chain": [],
                              "context_length": parameters["effective_context_size"]}
    return config


@contextmanager
def _routed(runtime):
    from agent.auxiliary_client import scoped_runtime_main
    from hermes_cli.config_read_scope import readonly_config_scope
    with scoped_runtime_main(runtime), readonly_config_scope(lambda cfg: project_config(cfg, runtime)):
        yield


@contextmanager
def turn_scope(request):
    if not is_local_llama_provider(request.provider):
        yield
        return
    from .binding import get_manager
    manager = get_manager(root=request.runtime_root, create=False)
    with manager.lease(request.model, request.turn_id or request.session_id or "local-turn",
                       request.persona_instance_id or "local-agent") as runtime:
        with _routed(runtime):
            yield


@contextmanager
def prewarm_scope(request):
    if not is_local_llama_provider(request.provider) or not request.prewarm_only:
        yield
        return
    with _routed(resolve(request.model, root=request.runtime_root)):
        yield


def construction_kwargs(runtime):
    if "local_parameters" not in runtime:
        return {}
    generation = runtime["local_parameters"]["generation"]
    return {"requested_provider": PROVIDER_ID, "max_tokens": generation["max_output_tokens"],
            "fallback_model": [], "request_overrides": {"temperature": generation["temperature"],
              "top_p": generation["top_p"], "extra_body": {"top_k": generation["top_k"]}}}


def actor_signature(runtime, original):
    if "local_parameters" not in runtime:
        return original
    # A reload with changed parameters or endpoint cannot reuse the prior client.
    digest = hashlib.sha256(json.dumps({"parameters": runtime["local_parameters"],
                                       "endpoint": runtime["base_url"], "credential": runtime["api_key"]},
                                      sort_keys=True).encode()).hexdigest()
    return original + ":local-llama:" + digest
