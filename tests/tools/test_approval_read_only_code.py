"""RT-FU-A-READ-ONLY-CHECK-IN-A-HELPERS-TERMINAL-WAITS-ON-AN-APPROVAL: on an Eternia chat turn a
``python -c`` or ``powershell -Command`` that only reads or waits is not flagged; one that could
write still is, and so is every one off a harness turn (upstream's surfaces keep upstream's rule).

Driven through ``detect_dangerous_command``, the entry the terminal guard uses, under the fork's
``scoped_approval_policy`` (what every persona chat turn's ``session_approval_scope`` binds).
Killing mutations (recorded in the landing commit): drop the seam call in
``approval_detection._execution_flag_findings`` -> the observed check reds; drop the
``_on_a_harness_turn`` test in ``read_only_code`` -> the off-turn case reds; drop the rebinding
refusal -> ``print = ...`` reds; drop ``_PS_REFUSED`` -> the redirection and method-call cases red.
"""

from __future__ import annotations

import pytest

from agent_runtime.approval_surface_policy import scoped_approval_policy
from tools.approval_detection import detect_dangerous_command

#: The helper's own check, byte for byte as ``command_full`` recorded it on 2026-11-20
#: (events.jsonl 00:03:52Z), its path shortened.
OBSERVED = (
    r"""git config --show-origin core.autocrlf; file 'queue.md'; python -c "from pathlib import Path; """
    r"""p=Path(r'queue.md'); b=p.read_bytes(); print('CRLF=', b.count(b'\\r\\n'), 'bare_LF=', """
    r"""b.count(b'\\n')-b.count(b'\\r\\n'), 'bare_CR=', b.count(b'\\r')-b.count(b'\\r\\n'))" """
).rstrip()


def _flagged_on_a_turn(command: str) -> bool:
    with scoped_approval_policy("manual"):
        return detect_dangerous_command(command)[0]


def test_the_observed_read_only_check_runs_without_an_approval_on_a_chat_turn():
    assert _flagged_on_a_turn(OBSERVED) is False


#: Seen again on the same helper (events.jsonl 00:41:27Z and 00:47:31Z), paths shortened: one line
#: of a queue note, and a wait on the helper's own background test followed by its log's tail.
SEEN_AGAIN = (
    r"""python -c "from pathlib import Path; n='QA-ROW'; line=next(x for x in Path('queue.md').read_text(encoding='utf-8').splitlines() if n in x); print(line[-850:])" """.rstrip(),
    r"""powershell.exe -NoProfile -Command '$id=21544; try { Wait-Process -Id $id -Timeout 570 -ErrorAction Stop; Write-Output "PROCESS_DONE" } catch { Write-Output "WAIT_FAILED_OR_TIMEOUT: $($_.Exception.Message)" }; if (-not (Get-Process -Id $id -ErrorAction SilentlyContinue)) { Get-Content "X:/w/qa_artifacts/claim_test.log" -Tail 80 }'""",
)


@pytest.mark.parametrize("command", SEEN_AGAIN)
def test_the_checks_seen_again_run_without_an_approval_on_a_chat_turn(command):
    assert _flagged_on_a_turn(command) is False


def test_off_a_harness_turn_python_c_keeps_upstreams_rule():
    assert detect_dangerous_command(OBSERVED)[0] is True
    assert detect_dangerous_command(SEEN_AGAIN[1])[0] is True


@pytest.mark.parametrize("command", [
    "python -c \"import os; os.system('whoami')\"",
    "python -c \"open('x', 'w').write('a')\"",
    "python -c \"from pathlib import Path; Path('x').write_text('a')\"",
    "python -c \"from pathlib import Path; Path('x').unlink()\"",
    "python -c \"from pathlib import Path; Path('a').replace('b')\"",
    "python -c \"from pathlib import Path; print = Path('x').unlink; print()\"",
    "python -c \"from pathlib import Path; Path.read_text = Path.unlink; Path('x').read_text()\"",
    "python -c \"import json as print; print.loads('1')\"",
    "python -c \"getattr(__builtins__, 'eval')('1')\"",
    "python -c \"().__class__.__base__\"",
    "python -c \"exec('1')\"",
    "python -c \"def f(): pass\"",
    "python -c \"import subprocess\"",
    "python -W ignore -c \"print(1)\"",
    "python -c \"print(1\"",
    "node -e \"console.log(1)\"",
    "powershell -NoProfile -Command 'Get-Content a.txt > b.txt'",
    "powershell -NoProfile -Command 'Get-Content a.txt | Set-Content b.txt'",
    "powershell -NoProfile -Command 'Remove-Item a.txt'",
    "powershell -NoProfile -Command 'rm a.txt'",
    "powershell -NoProfile -Command '(Get-Process -Id 1).Kill()'",
    "powershell -NoProfile -Command 'Get-Process -Id 1 | Stop-Process'",
    "powershell -NoProfile -Command 'Get-Process -Id 1 | ForEach-Object Kill'",
    "powershell -NoProfile -Command '& $env:X'",
    "powershell -NoProfile -Command '. ./x.ps1'",
    "powershell -NoProfile -Command '[IO.File]::WriteAllText(\"a\", \"b\")'",
    "powershell -NoProfile -Command 'Write-Output \"$(Remove-Item a.txt)\"'",
    "powershell -NoProfile -Command 'Get-Content a.txt' extra",
    "powershell -ExecutionPolicy Bypass -File helper.ps1",
])
def test_code_that_could_do_more_than_read_still_asks(command):
    assert _flagged_on_a_turn(command) is True


@pytest.mark.parametrize("command", [
    "python3 -c \"import json, sys; print(json.loads('[1]'), sys.argv)\"",
    "python -I -c \"import re; print(re.findall('a', 'banana'))\"",
    "py -c \"from collections import Counter; print(Counter('abca').most_common(1))\"",
])
def test_other_reads_run_without_an_approval(command):
    assert _flagged_on_a_turn(command) is False
