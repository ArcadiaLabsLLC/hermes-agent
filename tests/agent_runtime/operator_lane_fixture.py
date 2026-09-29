"""Deterministic real serve lanes; no socket, process, thread, provider or model."""
import threading
from concurrent.futures import Future
from types import SimpleNamespace

from hermes_cli.harness_parts.serve.handle_message import MessageHandling
from hermes_cli.harness_parts.serve.lanes import ArgvLanes


class OperatorLane(MessageHandling, ArgvLanes):
    def __init__(self, home, dispatch):
        self.serve_request_home = home
        self.dispatch = dispatch
        self.inflight_lock = threading.Lock()
        self.inflight, self.inflight_futures = {}, {}
        self.drain_state = None
        self.jobs, self.output = [], []
        self.frames = SimpleNamespace(emit=self.output.append)
        self.stdout_proxy = self.stderr_proxy = SimpleNamespace(flush_request=lambda _: None)
        self.pool = SimpleNamespace(submit=self.submit)

    def submit(self, function, *args):
        future = Future()
        self.jobs.append((function, args, future))
        return future

    def advance(self):
        function, args, future = self.jobs.pop(0)
        try:
            result = function(*args)
        except BaseException as exc:
            future.set_exception(exc)
            raise
        else:
            future.set_result(result)

    @staticmethod
    def _owner_of(_):
        return "stdio"

    def rpc(self, method, params):
        rid = f"rpc-{len(self.output)}"
        self._dispatch_rpc({"jsonrpc": "2.0", "id": rid, "method": method,
                            "params": params}, self.frames, None)
        replies = [row for row in self.output if row.get("id") == rid]
        return replies[-1] if replies else None
