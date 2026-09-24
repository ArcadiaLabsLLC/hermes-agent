"""Real-serve install fixtures shared by the gateway-peer e2e files.

``_Install`` (one ``harness serve`` child in its own sandbox) and the
``two_installs`` pair used to live in ``test_gateway_peer_two_roots_e2e.py``,
with a byte-identical copy of the fixture in the cross-install chat file; the
two e2e files and the media one now take both from here.

Measured 2026-09-24 (``docs/agent-runtime-harness/planned/
suite-cost-centres-2026-09-24.md`` §2): these files pay 5-6 s of setup per
TEST, which is the two serve boots run one after the other. They now boot side
by side (:func:`boot_together`). The boots are NOT shared across tests; the
fixture's docstring records why for the pair, and the lifecycle files
(``test_serve_socket_child_e2e.py``, ``test_serve_ended_sidecar_child_e2e.py``)
say so at their own boot helper — in those, the boot and its ending are the
subject of the test.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOT_TIMEOUT_SECONDS = 180.0
CLI_TIMEOUT_SECONDS = 180.0


def _sandbox_env(base: Path) -> dict[str, str]:
    home = base / "home"
    local = base / "localappdata"
    for path in (home, local, base / "runtime"):
        path.mkdir(parents=True, exist_ok=True)
    # The gateway lane, turned on the way an operator's config would: a HOST
    # STRING (boolean `true` is refused by design) and port 0, so the kernel
    # picks and the `ready` frame publishes what it picked.
    (home / "config.yaml").write_bytes(
        b'remote_gateway:\n  listen: "127.0.0.1"\n  port: 0\n'
    )
    env = dict(os.environ)
    env.update(
        {
            "HERMES_AGENT_RUNTIME_ROOT": str(base / "runtime"),
            "HERMES_HOME": str(home),
            # The EXPLICIT head, exactly as the Launcher always starts serve
            # (`HERMES_HOME=profiles/<profile>`, `HERMES_HEAD_HOME=profiles/base`;
            # one profile here, so one directory). It is load-bearing rather
            # than decoration: ``publish_chat_head_home`` is a no-op for a
            # process that named no head, so without this the boot publishes no
            # chat-head pointer and every in-serve transcript read degrades to
            # the ambient rung — which is env-gated and refuses.
            #
            # S2b's ``peer.thread.read`` found that live: the far read came back
            # ``thread_unreadable / chat_scope_unresolved``, which is the
            # CORRECT failure (closed, typed, never an empty page) for a runtime
            # nobody told where the transcripts live. Setting the head here
            # makes the sandbox model the configuration that actually ships,
            # instead of one no launcher produces.
            "HERMES_HEAD_HOME": str(home),
            "LOCALAPPDATA": str(local),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PYTHONPATH": str(REPO_ROOT) + os.pathsep + str(env.get("PYTHONPATH") or ""),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


class _Install:
    """One serve child: its env, its process, and the facts its boot published."""

    def __init__(self, name: str, base: Path) -> None:
        self.name = name
        self.base = base
        self.env = _sandbox_env(base)
        self.process: subprocess.Popen | None = None
        self.ready: dict = {}

    @property
    def root(self) -> Path:
        return self.base / "runtime"

    @property
    def gateway_port(self) -> int:
        return int(self.ready["gateway"]["port"])

    def start(self) -> None:
        self.launch()
        self.await_ready()

    def launch(self) -> None:
        """Spawn the serve child without waiting for its ``ready`` frame, so
        several installs can boot side by side (:func:`boot_together`)."""

        self.process = subprocess.Popen(
            [sys.executable, "-m", "hermes_cli.main", "harness", "serve", "--ndjson"],
            cwd=str(REPO_ROOT),
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    def await_ready(self) -> None:
        self.ready = self._wait_for("ready")

    def _wait_for(self, event: str, timeout: float = BOOT_TIMEOUT_SECONDS) -> dict:
        assert self.process is not None
        deadline = time.monotonic() + timeout
        seen: list[str] = []
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if not line:
                raise AssertionError(
                    f"{self.name}: serve child ended before {event!r}; saw {seen}"
                )
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            seen.append(frame.get("event"))
            if frame.get("event") == event:
                return frame
        raise AssertionError(f"{self.name}: no {event!r} within {timeout}s; saw {seen}")

    def cli(self, *argv: str) -> tuple[int, dict | None, str]:
        """Run one operator verb against THIS install, as its own process."""

        completed = subprocess.run(
            [sys.executable, "-m", "hermes_cli.main", "harness", *argv, "--json"],
            cwd=str(REPO_ROOT),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
        )
        payload = None
        stdout = completed.stdout or ""
        start = stdout.find("{")
        if start >= 0:
            try:
                payload = json.loads(stdout[start:])
            except json.JSONDecodeError:
                payload = None
        return completed.returncode, payload, stdout + (completed.stderr or "")

    def python(self, source: str, *args: str) -> tuple[int, str]:
        """Run a snippet inside THIS install's environment.

        Used for the A→B dial, which has no CLI verb of its own in Stage 6 —
        ``peer.ping`` is the wire proof rather than an operator surface, and
        inventing a verb to make a test convenient would ship an operator door
        nobody asked for.

        ``*args`` land on the snippet's ``sys.argv`` (Stage 7, whose acceptance
        parameterises the same snippet over a target spelling and a method
        name). Variadic and defaulted to nothing, so the Stage 6 snippets that
        read ``sys.argv[1] if len(sys.argv) > 1`` behave exactly as they did.
        """

        completed = subprocess.run(
            [sys.executable, "-c", source, *args],
            cwd=str(REPO_ROOT),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
        )
        return completed.returncode, (completed.stdout or "") + (completed.stderr or "")

    def stop(self) -> None:
        if self.process is None:
            return
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.kill()



def boot_together(installs: list[_Install]) -> None:
    """Spawn every install first, then wait for each ``ready``.

    The children are isolated from each other by construction (own runtime
    root, ``HOME``, ``LOCALAPPDATA``, ``HERMES_HOME`` — :func:`_sandbox_env`),
    so nothing orders their boots; waiting for A before spawning B only
    serialised two cold interpreter starts (5-6 s each on this box, the
    suite-cost note's per-test setup). If one never gets ready, every child
    already spawned is stopped before the failure propagates.
    """

    try:
        for install in installs:
            install.launch()
        for install in installs:
            install.await_ready()
    except BaseException:
        for install in installs:
            install.stop()
        raise


@pytest.fixture
def two_installs(tmp_path):
    """Two real serves, fresh per TEST — deliberately not per module.

    Every test that takes this fixture runs a pairing ceremony against the
    pair and asserts on what it leaves behind, and part of what it leaves is
    outside ``gateway/`` where no reset can reach it under a running serve:
    the event log (``test_a_completed_join_leaves_both_caches_saying_reachable``
    asserts a ``gateway.peer.reachability`` row is in the tail — a shared
    serve would satisfy it with the PREVIOUS test's row), seeded personas and
    far threads, and revocation pushes that land asynchronously on the other
    serve. Sharing the boot would turn those assertions into assertions about
    another test. The saving is taken instead by booting the two side by side.
    """

    installs = [_Install("A", tmp_path / "a"), _Install("B", tmp_path / "b")]
    boot_together(installs)
    try:
        yield installs
    finally:
        for install in installs:
            install.stop()


