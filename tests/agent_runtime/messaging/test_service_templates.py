"""p10-messaging M5: the three OS-scheduler templates start the runtime as a service the way the serve expects.

Owner RULED 2026-10-19: v1's service is a documented template, not an installer. Each template must start
``harness serve --ndjson --service`` with NO ``--parent-pid`` (nothing owns a service; a parent pid would drain it
when the starter exits) and with stdin closed (EOF is what detaches a ``--service`` serve), and must parse as
its OS reads it. Killing mutation: add ``--parent-pid 1`` to any template's argv →
``test_each_template_starts_a_parentless_service`` red.
"""

from __future__ import annotations

import plistlib
import shlex
from pathlib import Path
from xml.etree import ElementTree

import pytest

SERVICE = Path(__file__).resolve().parents[3] / "docs" / "agent-runtime-harness" / "reference" / "service"
TASK_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def _windows() -> tuple[list[str], bool]:
    exec_ = ElementTree.parse(SERVICE / "windows-task.xml").getroot().find("t:Actions/t:Exec", TASK_NS)
    arguments = exec_.find("t:Arguments", TASK_NS).text
    serve = arguments.split("&&", 1)[1]
    return shlex.split(serve.replace("<NUL", ""), posix=False)[1:], "<NUL" in serve


def _systemd() -> tuple[list[str], bool]:
    lines = dict(line.split("=", 1) for line in (SERVICE / "hermes-serve.service").read_text(encoding="utf-8")
                 .splitlines() if "=" in line and not line.startswith("#"))
    return shlex.split(lines["ExecStart"])[1:], lines.get("StandardInput") == "null"


def _launchd() -> tuple[list[str], bool]:
    with (SERVICE / "com.eternia.hermes-serve.plist").open("rb") as handle:
        plist = plistlib.load(handle)
    return list(plist["ProgramArguments"][1:]), plist.get("StandardInPath") == "/dev/null"


@pytest.mark.parametrize("read", [_windows, _systemd, _launchd], ids=["windows", "systemd", "launchd"])
def test_each_template_starts_a_parentless_service(read):
    argv, stdin_closed = read()
    assert argv == ["harness", "serve", "--ndjson", "--service"]
    assert not any(arg.startswith("--parent-pid") for arg in argv)
    assert stdin_closed


def test_the_stop_is_a_drain_where_the_os_cannot_signal_one():
    unit = (SERVICE / "hermes-serve.service").read_text(encoding="utf-8")
    assert "ExecStop=" in unit and "harness serve connect --drain" in unit
    task = (SERVICE / "windows-task.xml").read_text(encoding="utf-8")
    assert "hermes harness serve connect" in task  # Task Scheduler's End is TerminateProcess
