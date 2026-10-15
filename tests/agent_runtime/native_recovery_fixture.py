"""Cross-repository test entry: real RPC handlers, native workers and loopback model."""
import json
import os
from pathlib import Path
import sys
import threading
from concurrent.futures import ThreadPoolExecutor


def main():
    home = Path(os.environ["HERMES_HOME"]).resolve(strict=True)
    if os.environ.get("HERMES_TEST_ISOLATION") != str(home) or any(home.iterdir()):
        raise RuntimeError("An empty isolated Hermes home is required")
    wire, sys.stdout = sys.stdout, sys.stderr
    from tests.agent_runtime.native_recovery_provider import RecoveryProvider
    provider = RecoveryProvider()
    provider.configure(home, compute=True)
    from agent_runtime.conversations import binding
    from agent_runtime.execution_identity import execution_identity
    from agent_runtime.serve_rpc import handle_request
    from agent_runtime.serve_rpc.protocol import RpcContext, is_deferred

    root = home / "runtime"
    root.mkdir()
    binding.bind(root, "isolated-native")
    lock = threading.Lock()
    def write(frame):
        with lock:
            print(json.dumps(frame, ensure_ascii=True), file=wire, flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        def spawn(build):
            pool.submit(lambda: write(build()))
            return True
        context = RpcContext(spawn_reply=spawn)
        write({"ready": True, "execution_id": execution_identity()["execution_id"]})
        try:
            for line in sys.stdin:
                frame = json.loads(line)
                if frame["method"] == "fixture.release":
                    provider.release.set()
                    write({"id": frame["id"], "result": {"requests": len(provider.requests)}})
                    continue
                response = handle_request(frame, context)
                if not is_deferred(response):
                    write(response)
        finally:
            provider.release.set()
            binding.shutdown(root=root)
            provider.close()


if __name__ == "__main__":
    main()
