"""Exact operator interruption on the existing serve inflight table."""
from contextlib import contextmanager

from agent.interrupt_scope import bind_interrupt_scope
from agent_runtime.chat_turn_reservations import (
    STATE_ACCEPTED, read_chat_turn_receipt,
)

__layer__ = "lanes"


def interrupt_operator_turn(serve, turn_id: str) -> bool:
    with serve.inflight_lock:
        request = next((item for item in serve.inflight.values()
                        if item.turn_request_id == turn_id), None)
    if request is None:
        return False
    request.interrupt_scope.cancel("Stopped by the user", tool_reason=None)
    return True


@contextmanager
def operator_interrupt_scope(request):
    """Bind upstream interruption, including Stop received while queued."""
    receipt = read_chat_turn_receipt(request.turn_request_id) if request.turn_request_id else None
    if receipt is not None and receipt.state == STATE_ACCEPTED and receipt.stop_requested:
        request.interrupt_scope.cancel("Stopped by the user", tool_reason=None)
    with bind_interrupt_scope(request.interrupt_scope):
        yield request.interrupt_scope.reason is not None
