"""Result delivery shared by local CLI and direct native operation adapters."""
from __future__ import annotations
__layer__ = "policy"

def emit_operation_result(args, payload: dict, human: str | None = None) -> None:
    sink = getattr(args, "operation_result_sink", None)
    if sink is not None:
        sink(payload)
        return
    from agent_runtime.cli_format import emit_json
    print(emit_json(payload) if args.json else (human or payload.get("error") or str(payload)))
