"""Explicit isolated official binary install/activation proof (never the live home)."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--backend", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_HOME"] = str(output / "home")
    os.environ["HERMES_AGENT_RUNTIME_ROOT"] = str(output / "runtime")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agent_runtime.local_llama.manager import LocalLlamaManager
    manager = LocalLlamaManager(output / "runtime", output / "home" / "config.yaml", "isolated-setup-proof")
    receipt = {"complete": False, "tag": args.tag}
    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    def guards(**extra):
        status = manager.status()
        return {"request_id": str(uuid.uuid4()), "expect_epoch": status["epoch"],
                "expect_revision": status["revision"], "expect_config_revision": status["config_revision"], **extra}
    def wait(request):
        last = None
        end = time.monotonic() + 1800
        while time.monotonic() < end:
            op = manager.setup.status(request_id=request["request_id"])["requested_operation"]
            if op["phase"] != last:
                print(op["phase"], flush=True)
                last = op["phase"]
            if op["state"] not in ("queued", "running", "cancelling"):
                return op
            time.sleep(.2)
        raise TimeoutError("setup proof deadline")
    try:
        row = manager.setup.catalog.release(args.tag)
        plan = manager.setup.plan({"tag": args.tag, "release_id": str(row["id"]),
            "variant_id": "win-x64-" + args.backend, "destination_parent": str(output)})["plan"]
        receipt["plan"] = plan
        save()
        request = guards(plan_id=plan["plan_id"], plan_revision=1, acknowledged_warning_ids=plan["warning_ids"])
        first = manager.setup.submit("install", request)
        assert manager.setup.submit("install", request)["operation"]["operation_id"] == first["operation"]["operation_id"]
        receipt["install"] = wait(request)
        save()
        assert receipt["install"]["state"] == "succeeded", receipt["install"]
        assert manager.config["executable_path"] is None and manager.server == "off"
        inventory = manager.setup.status()
        chosen = inventory["inventory"][0]
        activate = guards(installation_id=chosen["installation_id"], expect_inventory_revision=inventory["inventory_revision"])
        manager.setup.submit("activate", activate)
        receipt["activation"] = wait(activate)
        assert receipt["activation"]["state"] == "succeeded", receipt["activation"]
        assert manager.config["executable_path"] == chosen["executable_path"] and manager.server == "off"
        receipt["installation"] = chosen
        receipt["complete"] = True
        save()
        print("complete", flush=True)
    finally:
        manager.close()


if __name__ == "__main__":
    main()
