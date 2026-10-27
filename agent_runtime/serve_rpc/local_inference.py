"""``runtime.embed.texts`` and ``runtime.vision.tag`` — small local ONNX models on the speech pack.

Translation shims over :mod:`agent_runtime.local_inference.service`; the contract a client
integrates from is ``docs/agent-runtime-harness/runtime-local-inference-methods.md``. Both load a
model and spend CPU inference, so both are ``console`` tier and answer on the transport's worker
lane when it has one.
"""

from __future__ import annotations

from typing import Any, Callable

from agent_runtime.call_authorization import TIER_CONSOLE

from agent_runtime.serve_rpc.protocol import (
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    RpcContext,
    defer_or_inline,
    err,
    ok,
)
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["_runtime_embed_texts", "_runtime_vision_tag"]

_REFUSAL_CODES = {"invalid_params": ERR_INVALID_PARAMS, "not_found": ERR_NOT_FOUND, "conflict": ERR_CONFLICT}


def _inference_frame(rid: Any, method_name: str, run: Callable[[Any], dict], params: Any) -> dict:
    from agent_runtime.local_inference.models import LocalInferenceRefused

    try:
        return ok(rid, run(params))
    except LocalInferenceRefused as refusal:
        return err(rid, _REFUSAL_CODES.get(refusal.code, ERR_HANDLER_FAILED),
                   f"{method_name} refused: {refusal.reason}", {"reason": refusal.reason, **refusal.data})
    except Exception as exc:  # the class name only
        return err(rid, ERR_HANDLER_FAILED, f"{method_name} failed",
                   {"reason": "handler_failed", "method": method_name, "error_class": type(exc).__name__})


def _service():
    from agent_runtime.local_inference.service import service

    return service()


@method("runtime.embed.texts", tier=TIER_CONSOLE)
def _runtime_embed_texts(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Embed up to 64 texts. Params: ``model`` (``bge-small-en-v1.5``), ``models_dir``, ``texts``.
    Result: ``{contract, model, dim, encoding, vectors}`` (base64 little-endian float32, unit length)."""
    name = "runtime.embed.texts"
    return defer_or_inline(rid, name, context, lambda: _inference_frame(rid, name, _service().embed_texts, params))


@method("runtime.vision.tag", tier=TIER_CONSOLE)
def _runtime_vision_tag(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Zero-shot tag one image. Params: ``model`` (``clip-vit-base-patch32``), ``models_dir``,
    ``image`` (base64, at most 2 MiB), ``labels``, ``top_k``. Result: ``{contract, model, scores}``."""
    name = "runtime.vision.tag"
    return defer_or_inline(rid, name, context, lambda: _inference_frame(rid, name, _service().tag_image, params))
