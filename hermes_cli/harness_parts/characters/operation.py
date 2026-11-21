"""The ``harness characters`` generation verbs as typed calls on the running Hermes.

Row ``RT-EVERY-ACTION-ETERNIA-SENDS-HAS-A-TYPED-CALL-ON-THE-RUNNING-HERMES``: each ``runtime.characters.<verb>``
runs the argv handler itself through the operation-result sink (the ``model_operation_result`` seam), so the
draft calls, the refusals (``ok: false`` + ``error`` …) and the payload are that verb's, byte for byte as
``--json`` prints them. ``params`` here are already shape-checked by ``serve_rpc.characters``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from agent_runtime.cli_format import emit_json

__layer__ = "lanes"
__all__ = ["CHARACTER_VERBS", "characters_operation_result"]


def _handlers() -> dict[str, Any]:
    from . import auto, commands, steps

    return {
        "base": commands._cmd_characters_base,
        "turnaround": steps._cmd_characters_turnaround,
        "reroll_direction": steps._cmd_characters_reroll_direction,
        "approve_direction": steps._cmd_characters_approve_direction,
        "rows": steps._cmd_characters_rows,
        "reroll_row": steps._cmd_characters_reroll_row,
        "compose": steps._cmd_characters_compose,
        "auto": auto._cmd_characters_auto,
        "reopen": commands._cmd_characters_reopen,
        "add_state": commands._cmd_characters_add_state,
    }


#: verb -> the argv namespace it reads, built from the method's params (lists joined the way the flag takes them).
CHARACTER_VERBS = ("base", "turnaround", "reroll_direction", "approve_direction", "rows", "reroll_row",
                   "compose", "auto", "reopen", "add_state")


def _joined(params: dict, key: str) -> str:
    return ",".join(params.get(key) or [])


#: verb -> the argv flags it reads beyond ``--draft``, built from the method's params (a list joined the way
#: the comma-separated flag takes it). A table, so a new verb is one row.
_FLAGS: dict[str, Any] = {
    "base": lambda p: {"image": p["image"]},
    "turnaround": lambda p: {},
    "reroll_direction": lambda p: {"direction": p["direction"], "note": p.get("note") or ""},
    "approve_direction": lambda p: {"direction": p.get("direction") or "", "approve_all": bool(p.get("all")),
                                    "attempt": p.get("attempt", -1)},
    "rows": lambda p: {"only": _joined(p, "only")},
    "reroll_row": lambda p: {"row": p["row"], "note": p.get("note") or ""},
    "compose": lambda p: {"accept_handedness": _joined(p, "accept_handedness")},
    "auto": lambda p: {"through": p.get("through") or "compose"},
    "reopen": lambda p: {},
    "add_state": lambda p: {"state": p["state"]},
}


def _namespace(verb: str, params: dict) -> SimpleNamespace:
    return SimpleNamespace(draft=params["draft"], **_FLAGS[verb](params), json=True)


def characters_operation_result(verb: str, params: dict) -> dict:
    """One verb's payload. ``auto`` answers its SUMMARY line with every earlier receipt as ``receipts``."""
    rows: list[dict] = []
    args = _namespace(verb, params)
    args.operation_result_sink = rows.append
    _handlers()[verb](args)
    if not rows:
        raise RuntimeError(f"characters {verb} produced no result")
    encoded = [json.loads(emit_json(row)) for row in rows]
    if verb == "auto":
        return {**encoded[-1], "receipts": encoded[:-1]}
    if len(encoded) != 1:
        raise RuntimeError(f"characters {verb} produced {len(encoded)} results")
    return encoded[0]
