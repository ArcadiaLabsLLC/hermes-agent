"""Fork seams of ``scripts/run_tests_parallel.py`` (lane pb-a, footprint audit 2026-10-15).

The upstream runner calls into this module at one site; everything the fork adds to
how a per-file subprocess is spawned lives here, not in the upstream file.

On Windows the per-file child runs under ``python -I -S scripts/_fork_runner.py --job
-- <argv>`` (``job_wrap``): the wrapper puts itself in a Job Object with
KILL_ON_JOB_CLOSE, so every process the test file starts is killed when the wrapper
exits, even one whose parent already exited. The upstream runner's ``taskkill /T``
walks the parent chain and cannot reach such an orphan: ``tests/docker/``'s
``docker build`` left ``docker.exe``/``buildx`` holding the base worktree that way
(fork-hygiene row, r-fastgate ``--confirm-red`` 2026-10-16).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

COVERAGE_RC_ENV = "HERMES_TEST_COVERAGE_RC"
#: test files whose red writes real machine state (the user PATH, the registry): run once,
#: alone, never re-run (``run_once``). One repo-relative path per line; ``#`` starts the why.
RUN_ONCE_LIST = Path(__file__).resolve().parent / "test_files_run_once.txt"
#: the argument that makes this file a Job Object wrapper (``__main__``)
JOB_FLAG = "--job"


def run_once_list(path: Path = RUN_ONCE_LIST) -> frozenset[str]:
    """The listed files (repo-relative POSIX); a missing list is empty."""

    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return frozenset()
    return frozenset(entry for line in lines if (entry := line.split("#", 1)[0].strip()))


def run_once(file: Path, listed: frozenset[str] | None = None) -> bool:
    """Whether ``file`` is on the run-once list: the upstream runner's retry loop stops on it
    (``run_tests_parallel._run_one_file``), so a red that wrote the user PATH writes it once
    (build-1011-B5 D3.15: the install.ps1 fence mutation wrote it twice). The bundled runner
    runs a listed file alone and never shards it (``run_tests_bundled.load_unbundled``)."""

    listed = run_once_list() if listed is None else listed
    if not listed:
        return False
    try:
        rel = Path(os.path.relpath(_abs(file), RUN_ONCE_LIST.parent.parent)).as_posix()
    except ValueError:  # another drive than the checkout: no repo-relative name, so not listed
        return False
    return rel in listed


def _abs(file) -> str:
    return os.path.abspath(str(file))


def job_prefix() -> list[str]:
    """The argv that runs a command under ``job_wrap`` on Windows; nothing elsewhere."""

    if sys.platform != "win32":
        return []
    return [sys.executable, "-I", "-S", str(Path(__file__).resolve()), JOB_FLAG, "--"]


#: pytest short flags that consume the next token (the upstream runner's ``PYTEST_VALUE_FLAGS``)
_VALUE_FLAGS = frozenset({"-k", "-m", "-p", "-o", "-c", "-r", "-W"})


def _file_key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def node_selectors(argv: list[str]) -> tuple[dict[str, list[str]], str | None]:
    """The node ids named on the runner's command line, by file, and the ``-k`` expression
    the upstream runner injects for them (its node-id translation: every file runs with
    ``-k <leaf or leaf…>``, so a file named beside a node id ran 0 tests — q-runner,
    2026-10-18). Tokens after ``--`` and values of value-taking flags are not paths."""

    nodes: dict[str, list[str]] = {}
    leaves: list[str] = []
    previous = ""
    for token in argv:
        if token == "--":
            break
        if "::" in token and not token.startswith("-") and previous not in _VALUE_FLAGS:
            file_part, _, selector = token.partition("::")
            nodes.setdefault(_file_key(file_part), []).append(selector)
            leaves.append(selector.rsplit("::", 1)[-1].split("[", 1)[0])
        previous = token
    return nodes, (" or ".join(dict.fromkeys(leaves)) if leaves else None)


def _select_nodes(file: Path, pytest_args: list[str], argv: list[str]) -> tuple[list[str], list[str]]:
    """``(targets, pytest_args)`` for one file: when the upstream runner injected its node-id
    ``-k``, drop it and name the file's own node ids instead (a file named plainly runs whole)."""

    nodes, expr = node_selectors(argv)
    pair = next((i for i in range(len(pytest_args) - 1) if pytest_args[i:i + 2] == ["-k", expr]), None)
    if expr is None or pair is None:
        return [str(file)], pytest_args
    args = pytest_args[:pair] + pytest_args[pair + 2:]
    selectors = nodes.get(_file_key(file))
    return ([f"{file}::{sel}" for sel in selectors] if selectors else [str(file)]), args


def pytest_argv(file: Path, pytest_args: list[str], argv: list[str] | None = None) -> list[str]:
    """``python -m pytest <file> …``, wrapped in ``coverage run`` when asked, and in
    the Job Object wrapper on Windows (``job_prefix``). A file the command line named
    by node id runs those nodes; every other file runs whole (``_select_nodes``).

    The coverage wrap is the seam ``scripts/unreachable_branch_report.py`` measures
    through. Without it the report would have to re-implement ``run_tests.sh``'s
    hermetic environment to trace anything, and a second spelling of that
    environment is a second thing to keep in sync — the report would then be
    measuring branches under pins and env the suite never runs with.

    Absent-safe by construction: with the variable unset the pytest argv is
    byte-identical to what this runner has always spawned, so an ordinary run
    pays nothing and cannot be traced by accident. Every other decision
    (``branch``, ``parallel``, ``data_file``, ``source``) lives in the config
    file the report writes, so this seam carries ONE path and no policy.
    """
    rcfile = os.environ.get(COVERAGE_RC_ENV, "").strip()
    prefix = ["-m", "coverage", "run", f"--rcfile={rcfile}"] if rcfile else []
    targets, pytest_args = _select_nodes(file, pytest_args, sys.argv[1:] if argv is None else argv)
    return [*job_prefix(), sys.executable, *prefix, "-m", "pytest", *targets, *pytest_args]


_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


def enter_kill_on_close_job():
    """Put this process in a new Job Object that kills its members when its last
    handle closes (this process's exit). Returns the handle, or None when Windows
    refused (the command then runs unwrapped, as before)."""

    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
        ]

    class _Io(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _Extended(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                            ctypes.byref(info), ctypes.sizeof(info)):
        return None
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        return None
    return job


def job_wrap(argv: list[str]) -> int:
    """Run ``argv`` (stdio inherited) inside a kill-on-close Job Object; its exit code."""

    import subprocess

    job = enter_kill_on_close_job()  # held until this process exits  # noqa: F841
    try:
        return subprocess.call(argv)
    except KeyboardInterrupt:
        return 130


def _exit(code: int) -> None:
    """Exit with ``code`` as Windows reports it (an NTSTATUS does not fit a C long)."""

    if sys.platform == "win32" and code > 0x7FFFFFFF:
        import ctypes

        sys.stdout.flush()
        ctypes.WinDLL("kernel32").ExitProcess(ctypes.c_uint(code))
    sys.exit(code)


if __name__ == "__main__" and sys.argv[1:3] == [JOB_FLAG, "--"]:
    _exit(job_wrap(sys.argv[3:]))
