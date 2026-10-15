"""The ONE expected serve-RPC manifest every manifest-pinning test compares against.

Six tests used to pin a hand-typed copy of ``serve_rpc.manifest()`` each, and
all six drifted together the day the ``runtime.discussion.*`` / ``level`` /
``map`` families joined: 35 names typed, 78 live, nothing to regenerate them
from. The expectation now lives once, in ``serve_rpc_manifest.expected.json``
beside this file, and is WRITTEN by the producer:

    python -m tests.agent_runtime._serve_rpc_manifest --write

A change to the method set, a tier or the chat-verb params therefore shows up
as a diff to that one reviewed file — never as six hand edits — and a method
that silently drops out of the registry reds every test that reads it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_PATH = Path(__file__).with_name("serve_rpc_manifest.expected.json")


def render(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def expected_manifest() -> dict[str, Any]:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def expected_methods() -> list[str]:
    return list(expected_manifest()["methods"])


def main(argv: list[str]) -> int:
    from agent_runtime import serve_rpc

    live = render(serve_rpc.manifest())
    if argv[:1] == ["--write"]:
        EXPECTED_PATH.write_text(live, encoding="utf-8", newline="\n")
        print(f"wrote {EXPECTED_PATH.name}: {len(serve_rpc.manifest()['methods'])} methods")
        return 0
    same = EXPECTED_PATH.is_file() and EXPECTED_PATH.read_text(encoding="utf-8") == live
    print("up to date" if same else "stale: run `python -m tests.agent_runtime._serve_rpc_manifest --write`")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
