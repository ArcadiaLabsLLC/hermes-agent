"""``runtime.speech.*`` — status, load/unload, streaming recognize, synthesize.

Translation shims over :mod:`agent_runtime.speech_service`; the contract a
client integrates from is ``docs/agent-runtime-harness/runtime-speech-methods.md``.
Audio rides the method lane as base64 PCM inside frames (~32 KB/s in, one
chunk per push; synthesized audio comes back as ``runtime.speech.synthesize.chunk``
notifications). Recognition text comes back as ``runtime.speech.recognize.partial``
/ ``.final`` notifications to the caller's own connection.

Tiers follow ``runtime.local_llama.*``: ``status`` is ``read``, every verb that
loads a model or spends inference is ``console``.
"""

from __future__ import annotations

from concurrent.futures import Future
from typing import Any, Callable

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ

from agent_runtime.serve_rpc.protocol import (
    DEFERRED,
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    RpcContext,
    deferred_reply,
    err,
    ok,
)
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "FINAL_TIMEOUT_SECONDS",
    "_runtime_speech_load",
    "_runtime_speech_recognize_begin",
    "_runtime_speech_recognize_cancel",
    "_runtime_speech_recognize_end",
    "_runtime_speech_recognize_push",
    "_runtime_speech_status",
    "_runtime_speech_synthesize",
    "_runtime_speech_unload",
]

#: The longest a deferred final / synthesis reply waits for its worker.
FINAL_TIMEOUT_SECONDS = 120.0

_FAMILY_CODES = {"invalid_params": ERR_INVALID_PARAMS, "conflict": ERR_CONFLICT, "not_found": ERR_NOT_FOUND}


def _service():
    from agent_runtime.speech_service import service

    return service()


def _refused(rid: Any, method_name: str, refusal) -> dict:
    code = _FAMILY_CODES.get(refusal.code, ERR_HANDLER_FAILED)
    return err(rid, code, f"{method_name} refused: {refusal.reason}", {"reason": refusal.reason, **refusal.data})


def _failed(rid: Any, method_name: str, exc: BaseException) -> dict:
    return err(rid, ERR_HANDLER_FAILED, f"{method_name} failed",
               {"reason": "handler_failed", "method": method_name, "error_class": type(exc).__name__})


def _params(params: Any) -> dict:
    return params if isinstance(params, dict) else {}


def _answer(rid: Any, method_name: str, work: Callable[[], Any]) -> dict:
    from agent_runtime.speech_service import SpeechRefused

    try:
        result = work()
        if isinstance(result, Future):
            result = result.result(timeout=FINAL_TIMEOUT_SECONDS)
        return ok(rid, result)
    except SpeechRefused as refusal:
        return _refused(rid, method_name, refusal)
    except Exception as exc:  # noqa: BLE001 - class name only
        return _failed(rid, method_name, exc)


def _deferred(rid: Any, method_name: str, context: RpcContext, future: Future) -> dict:
    """Answer a worker-run result on the same ``id``: on the transport's pool when it has one."""
    build = lambda: _answer(rid, method_name, lambda: future)  # noqa: E731
    if context.spawn_reply is not None and context.spawn_reply(deferred_reply(rid, method_name, build)):
        return DEFERRED
    return build()


def _emitter(context: RpcContext) -> Callable[[str, dict], bool] | None:
    return None if context.emit is None else context.push


@method("runtime.speech.status", tier=TIER_READ)
def _runtime_speech_status(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Both models' state (``unavailable`` + reason, ``available``, ``loading``, ``loaded``) and the
    admission budget. Params (optional): ``models_dir``, ``stt_model``, ``tts_voice`` to inspect."""
    return _answer(rid, "runtime.speech.status", lambda: _service().status(_params(params)))


@method("runtime.speech.load", tier=TIER_CONSOLE)
def _runtime_speech_load(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Load from explicit local paths. Params: ``models_dir``, ``stt_model``, ``tts_voice``, ``which``."""
    context = context or RpcContext()
    service = _service()
    work = lambda: service.load(_params(params))  # noqa: E731
    build = lambda: _answer(rid, "runtime.speech.load", work)  # noqa: E731
    if context.spawn_reply is not None and context.spawn_reply(deferred_reply(rid, "runtime.speech.load", build)):
        return DEFERRED
    return build()


@method("runtime.speech.unload", tier=TIER_CONSOLE)
def _runtime_speech_unload(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Unload and release the reservation. Params: ``which`` (``stt`` | ``tts`` | ``both``)."""
    return _answer(rid, "runtime.speech.unload", lambda: _service().unload(_params(params)))


@method("runtime.speech.recognize.begin", tier=TIER_CONSOLE)
def _runtime_speech_recognize_begin(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Open a stream. Params: ``sample_rate`` (16000), ``encoding`` (``pcm_s16le``), ``language`` (``en``)."""
    context = context or RpcContext()
    return _answer(rid, "runtime.speech.recognize.begin", lambda: _service().recognize_begin(
        _params(params), connection_key=context.connection_key, emit=_emitter(context)))


@method("runtime.speech.recognize.push", tier=TIER_CONSOLE)
def _runtime_speech_recognize_push(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Append one chunk. Params: ``stream_id``, ``seq`` (0, 1, …), ``audio`` (base64 PCM)."""
    context = context or RpcContext()
    return _answer(rid, "runtime.speech.recognize.push", lambda: _service().recognize_push(
        _params(params), connection_key=context.connection_key))


@method("runtime.speech.recognize.end", tier=TIER_CONSOLE)
def _runtime_speech_recognize_end(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Close the stream; the reply (and a ``.final`` event) carries the final text. Params: ``stream_id``."""
    from agent_runtime.speech_service import SpeechRefused

    context = context or RpcContext()
    try:
        future = _service().recognize_end(_params(params), connection_key=context.connection_key)
    except SpeechRefused as refusal:
        return _refused(rid, "runtime.speech.recognize.end", refusal)
    return _deferred(rid, "runtime.speech.recognize.end", context, future)


@method("runtime.speech.recognize.cancel", tier=TIER_CONSOLE)
def _runtime_speech_recognize_cancel(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Drop a stream without a result. Params: ``stream_id``."""
    context = context or RpcContext()
    return _answer(rid, "runtime.speech.recognize.cancel", lambda: _service().recognize_cancel(
        _params(params), connection_key=context.connection_key))


@method("runtime.speech.synthesize", tier=TIER_CONSOLE)
def _runtime_speech_synthesize(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Text in; audio out as ``runtime.speech.synthesize.chunk`` events, then this reply. Params: ``text``."""
    from agent_runtime.speech_service import SpeechRefused

    context = context or RpcContext()
    if context.emit is None:
        return err(rid, ERR_INVALID_PARAMS, "runtime.speech.synthesize refused: push_channel_required",
                   {"reason": "push_channel_required"})
    try:
        future = _service().synthesize(_params(params), emit=context.push)
    except SpeechRefused as refusal:
        return _refused(rid, "runtime.speech.synthesize", refusal)
    return _deferred(rid, "runtime.speech.synthesize", context, future)
