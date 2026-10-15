"""``runtime.admission.*`` — the one local-model memory budget, for another Hermes process.

Bundled Hermes owns the GPU/RAM budget on a desktop (architecture §5.1). When
full Hermes is the active install it still loads its own LLMs, so it reserves
here before it loads and releases after it unloads
(:mod:`agent_runtime.model_admission_client`). A caller over the wire is always
a REMOTE holder: its name is stored under ``remote:`` so it can never replace a
local reservation, it is never evicted (bundled Hermes cannot unload another
process's model), and it lapses unless renewed within ``lease_seconds``.
Contract: ``docs/agent-runtime-harness/runtime-speech-methods.md``.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ

from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "ADMISSION_CONTRACT",
    "REMOTE_PREFIX",
    "_runtime_admission_release",
    "_runtime_admission_reserve",
    "_runtime_admission_status",
]

ADMISSION_CONTRACT = 1
REMOTE_PREFIX = "remote:"


def _authority():
    from agent_runtime.model_admission import admission

    return admission()


def _params(params: Any) -> dict:
    return params if isinstance(params, dict) else {}


def _holder(params: dict) -> str | None:
    holder = params.get("holder")
    if not isinstance(holder, str) or not holder.strip() or len(holder) > 128:
        return None
    return REMOTE_PREFIX + holder.strip()


@method("runtime.admission.status", tier=TIER_READ)
def _runtime_admission_status(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Pools, capacities and every reservation. Params: none."""
    return ok(rid, {"contract": ADMISSION_CONTRACT, **_authority().status()})


@method("runtime.admission.reserve", tier=TIER_CONSOLE)
def _runtime_admission_reserve(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Reserve (or renew) before a load. Params: ``holder``, ``kind``, ``resource``, ``bytes``,
    ``lease_seconds`` (optional)."""
    from agent_runtime.model_admission import AdmissionRefused

    params = _params(params)
    holder = _holder(params)
    if holder is None:
        return err(rid, ERR_INVALID_PARAMS, "runtime.admission.reserve refused: holder_invalid",
                   {"reason": "holder_invalid"})
    try:
        granted = _authority().reserve(holder, kind=params.get("kind", "llm"), resource=params.get("resource"),
                                       bytes=params.get("bytes"), owner="remote",
                                       lease_seconds=params.get("lease_seconds"))
    except AdmissionRefused as refusal:
        code = ERR_CONFLICT if refusal.reason == "over_budget" else ERR_INVALID_PARAMS
        return err(rid, code, f"runtime.admission.reserve refused: {refusal.reason}",
                   {"reason": refusal.reason, **refusal.details})
    except (TypeError, ValueError):
        return err(rid, ERR_INVALID_PARAMS, "runtime.admission.reserve refused: lease_invalid",
                   {"reason": "lease_invalid"})
    return ok(rid, {"contract": ADMISSION_CONTRACT, **granted, "holder": params["holder"].strip()})


@method("runtime.admission.release", tier=TIER_CONSOLE)
def _runtime_admission_release(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Release after an unload. Params: ``holder``. Releasing an unknown holder is not an error."""
    params = _params(params)
    holder = _holder(params)
    if holder is None:
        return err(rid, ERR_INVALID_PARAMS, "runtime.admission.release refused: holder_invalid",
                   {"reason": "holder_invalid"})
    return ok(rid, {"contract": ADMISSION_CONTRACT, "holder": params["holder"].strip(),
                    "released": _authority().release(holder)})
