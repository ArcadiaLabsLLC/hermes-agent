"""The serve log never carries a URL path secret from httpx's request line (RT-HTTPX-URL-SECRET-LOG).

httpx logs ``HTTP Request: GET <url> ...`` at INFO on the ``httpx`` logger. A secret in a URL PATH
(``/bot<token>/getMe``) is not a shape ``agent.redact`` can know in general, so the guard is the
level: every ``hermes`` subcommand, ``harness serve`` included, imports ``hermes_cli.main``, whose
module-level ``setup_logging`` pins ``httpx`` at WARNING (``hermes_logging._NOISY_LOGGERS``).

Proved at runtime, through the real entry: a child process imports ``hermes_cli.main`` with the
runtime command's argv mode against a throwaway home, sends one httpx request carrying a path secret,
and the home's ``agent.log`` is read back.

Killing mutation: drop ``"httpx"`` from ``hermes_logging._NOISY_LOGGERS`` -> the request line
(and the secret) reaches ``agent.log`` -> red.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

SECRET = "9876543210-pathsecret-not-a-known-token-shape"
MARKER = "httpx-guard-anti-vacuity-marker"

_CHILD = textwrap.dedent(
    f"""
    import logging, sys
    # main picks the log mode from the FIRST positional; for the runtime's command that is
    # "harness" (mode "cli"), so this argv is its mode without naming the subcommand (the
    # conftest live-system guard refuses a child whose argv could boot a backend).
    sys.argv = ["hermes", "harness"]
    import hermes_cli.main  # noqa: F401  (module-level setup_logging, as every subcommand runs it)
    import httpx

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={{}}))
    with httpx.Client(transport=transport) as client:
        client.get("https://api.invalid/bot{SECRET}/getMe")
    # Anti-vacuity: a WARNING on the same logger DOES reach agent.log, so its absence
    # below is the level's doing, not a log file nobody writes.
    logging.getLogger("httpx").warning("{MARKER}")
    for handler in logging.getLogger().handlers:
        handler.flush()
    print("httpx_level", logging.getLogger("httpx").getEffectiveLevel())
    """
)


def test_a_serve_process_never_logs_an_httpx_request_url(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HERMES_HOME": str(home), "PYTHONIOENCODING": "utf-8"}
    repo_root = Path(__file__).resolve().parents[2]
    done = subprocess.run(
        [sys.executable, "-c", _CHILD], cwd=repo_root, env=env, capture_output=True,
        text=True, encoding="utf-8", timeout=180,
    )
    assert done.returncode == 0, done.stderr[-2000:]

    log = (home / "logs" / "agent.log").read_text(encoding="utf-8", errors="replace")
    assert MARKER in log, "the child's agent.log was not the file the serve writes"
    assert "HTTP Request" not in log
    assert SECRET not in log
    assert SECRET not in done.stdout + done.stderr
    assert "httpx_level 30" in done.stdout, done.stdout[-500:]
