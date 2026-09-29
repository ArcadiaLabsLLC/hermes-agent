"""The serve's third transport (in-memory pipe) and the shell seam it runs under — plan Stage 2
steps 1, 2 and 10.

* Golden parity: the same ``runtime.*`` requests through the desktop serve (stdio, daemon shell)
  and the embedded serve (in-memory pipe, embedded shell) produce identical frames.
* The shell split: the embedded serve spawns no process and writes no pid registry row; the
  desktop serve, run the same way, does both (the positive control).
* An embedded shell refuses the daemon-only levers.
"""

from __future__ import annotations

import subprocess

import pytest

from hermes_cli.harness_parts.serve.in_memory import InMemoryPipe
from hermes_cli.harness_parts.serve.session import ServeSession
from hermes_cli.harness_parts.serve.shell import EMBEDDED_NOT_APPLICABLE, EmbeddedShell
from tests.agent_runtime.serve_transport_parity import (
    assert_transport_parity,
    frame_differences,
    normalize,
    rpc,
    run_in_memory,
    run_stdio,
)

REQUESTS = [
    rpc("unknown", "runtime.nope"),
    rpc("bad-params", "runtime.office.get"),
    {"jsonrpc": "1.0", "id": "bad-version", "method": "runtime.office.get"},
    rpc("maps", "runtime.map.list"),
    rpc("admission", "runtime.admission.status"),
]


def test_the_same_runtime_requests_produce_identical_frames_over_both_transports(tmp_path, monkeypatch):
    result = assert_transport_parity(tmp_path, monkeypatch, REQUESTS)

    replies = result["normalized"]["by_id"]
    # The comparison had something to compare: every request was answered on both legs.
    assert {"unknown", "bad-params", "bad-version", "maps", "admission"} <= set(replies)
    assert replies["unknown"][0]["error"]["code"] == -32601
    # Positive control: the comparison is not vacuous — one changed reply is a difference.
    embedded = normalize(result["embedded"], tmp_path / "embedded-app")
    embedded["by_id"]["maps"] = [{**embedded["by_id"]["maps"][0], "result": {"maps": ["x"], "count": 1}}]
    assert frame_differences(result["normalized"], embedded)


def test_the_embedded_shell_spawns_nothing_and_advertises_nothing(tmp_path, monkeypatch):
    from agent_runtime.build_stamp import reset_build_stamp_cache

    spawned: list = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        spawned.append(args[0] if args else kwargs.get("args"))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", recording_popen)
    reset_build_stamp_cache()
    embedded = run_in_memory(REQUESTS, tmp_path / "embedded-app", monkeypatch)
    embedded_spawns = list(spawned)
    embedded_root = tmp_path / "embedded-app" / "hermes" / "agent-runtime"

    reset_build_stamp_cache()
    desktop = run_stdio(REQUESTS, tmp_path / "desktop-app", monkeypatch)
    desktop_root = tmp_path / "desktop-app" / "hermes" / "agent-runtime"
    reset_build_stamp_cache()

    ready = next(f for f in embedded if f.get("event") == "ready")
    assert embedded_spawns == []
    assert ready["instance"]["outcome"] == EMBEDDED_NOT_APPLICABLE
    assert ready["auth"]["token_file"] == EMBEDDED_NOT_APPLICABLE
    assert ready["build"]["source"] != "git"
    assert not (embedded_root / "serve_instances").exists()
    # Positive control: the desktop serve, same requests, same process, spawns git for its build
    # stamp and writes (then removes) its registry row.
    assert spawned[len(embedded_spawns):], "the desktop leg spawned nothing — the control is broken"
    assert (desktop_root / "serve_instances").is_dir()
    assert next(f for f in desktop if f.get("event") == "ready")["build"]["source"] == "git"


@pytest.mark.parametrize("lever", [{"socket_lane": True}, {"service": True},
                                   {"record_end_reason": True}, {"parent_pid": 1}])
def test_an_embedded_shell_refuses_the_daemon_levers(lever):
    with pytest.raises(ValueError, match="no process to own"):
        ServeSession(InMemoryPipe(), None, shell=EmbeddedShell(), **lever)
    # Positive control: the same shell with no lever constructs.
    ServeSession(InMemoryPipe(), None, shell=EmbeddedShell())
