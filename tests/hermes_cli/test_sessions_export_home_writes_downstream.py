"""RT-SESSIONS-EXPORT-HOME-WRITES: ``hermes sessions export`` leaves a WRITABLE home untouched.

The launcher's owner-chat import runs the export against the owner's home. The four boot writers
(scratch prune, file log handlers, boot bootstrap record, ``ensure_hermes_home``'s skeleton) each
read the fork-owned ``hermes_read_only_invocation.is_read_only_invocation`` in a ``# fork seam``
guard. The subprocess cases drive the real CLI entry; ``sessions list`` is the positive control —
the same home, one variable changed, and the writers MUST appear (the bootstrap's skeleton exactly
when the child reads a checkout identity: RT-WRITING-COMMAND-HOME-SKELETON).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_read_only_invocation import is_read_only_invocation

REPO_ROOT = Path(__file__).resolve().parents[2]
# SQLite's own WAL index: a ``mode=ro`` reader in a writable directory creates them; not a Hermes writer.
_SQLITE_SIDECARS = {"state.db-shm", "state.db-wal"}


@pytest.mark.parametrize(
    "argv",
    [
        ["hermes", "sessions", "export", "--session-id", "s1", "--format", "jsonl", "-"],
        ["hermes", "--profile", "owner", "sessions", "export", "-"],
        ["/x/hermes_cli/main.py", "sessions", "export", "--format=jsonl", "--dry-run"],
    ],
)
def test_sessions_export_is_read_only(argv):
    assert is_read_only_invocation(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["hermes", "sessions", "list"],
        ["hermes", "sessions", "export", "--session-id", "s1", "--delete-after-verified", "--yes"],
        ["hermes", "sessions", "export", "--delete-after", "--yes"],  # argparse accepts the prefix
        ["hermes", "sessions", "export", "--delete-after-verified=1"],
        ["hermes", "harness", "serve"],
        ["hermes"],
        [],
    ],
)
def test_other_invocations_are_not(argv):
    assert not is_read_only_invocation(argv)


def test_the_default_argv_is_the_process_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hermes", "sessions", "export", "-"])
    assert is_read_only_invocation()
    monkeypatch.setattr(sys, "argv", ["hermes", "sessions", "list"])
    assert not is_read_only_invocation()


@pytest.fixture
def seeded_home(tmp_path):
    import hermes_state

    home = tmp_path / "home"
    home.mkdir()
    with hermes_state.SessionDB(db_path=home / "state.db") as seed:
        seed.create_session("sess-home", source="cli")
        seed.append_message("sess-home", "user", "hello from the owner's home")
    for leftover in list(home.iterdir()):  # the bare checkpointed store, nothing else
        if leftover.name != "state.db":
            if leftover.is_dir():
                import shutil

                shutil.rmtree(leftover)
            else:
                leftover.unlink()
    return home


def _cli_env(home: Path, *, no_git: bool = False) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in {"TMPDIR", "TMP", "TEMP", "HERMES_SCRATCH_DIR"}}
    env["HERMES_HOME"] = str(home)
    env["PYTHONPATH"] = str(REPO_ROOT)
    if no_git:  # the interpreter's own directory only: no git on PATH, as on a box whose git is absent
        env["PATH"] = str(Path(sys.executable).parent)
    return env


def _run_cli(home: Path, *args: str, no_git: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "hermes_cli.main", *args],
        cwd=REPO_ROOT, env=_cli_env(home, no_git=no_git), capture_output=True, text=True, timeout=120, check=False,
    )


def _child_install_identity(tmp_path: Path, *, no_git: bool) -> str:
    """The checkout identity a CLI child with this env reads (``boot_bootstrap.current_install_identity``), asked
    under a scratch home of its own so the probe never writes the home under test."""

    probe = tmp_path / "identity-probe-home"
    probe.mkdir(exist_ok=True)
    code = ("import sys; from pathlib import Path; from hermes_cli.boot_bootstrap import current_install_identity; "
            "print(current_install_identity(Path(sys.argv[1])) or '')")
    done = subprocess.run([sys.executable, "-c", code, str(REPO_ROOT)], cwd=REPO_ROOT,
                          env=_cli_env(probe, no_git=no_git), capture_output=True, text=True, timeout=60, check=True)
    return done.stdout.strip()


def _tree(home: Path) -> set[str]:
    return {str(p.relative_to(home)) for p in home.rglob("*")} - _SQLITE_SIDECARS


def test_export_leaves_a_writable_home_untouched(seeded_home):
    before = _tree(seeded_home)

    result = _run_cli(seeded_home, "sessions", "export", "--session-id", "sess-home", "--format", "jsonl", "-")

    assert result.returncode == 0, result.stderr
    assert "hello from the owner's home" in result.stdout
    assert _tree(seeded_home) == before == {"state.db"}


#: Written by every writing command: the file log handlers and the scratch prune.
_ALWAYS_WRITTEN = ("logs/agent.log", "cache/scratch/.last_prune")
#: Written only by the boot bootstrap's home steps, which run once per readable checkout identity and are
#: skipped, fail-open, when the child cannot read one (``boot_bootstrap.current_install_identity`` is None).
_BOOTSTRAP_WRITTEN = ("SOUL.md", "memories")


@pytest.mark.parametrize("no_git", [False, True], ids=["git", "no-git"])
def test_positive_control_a_writing_command_still_builds_the_skeleton(seeded_home, tmp_path, no_git):
    """RT-WRITING-COMMAND-HOME-SKELETON: the control asserted SOUL.md unconditionally, but SOUL.md (and
    ``memories``, the bootstrap record) come only from the boot bootstrap, which skips when the CLI child reads no
    checkout identity — no git on its PATH, or a git that refuses the checkout (Windows "dubious ownership").
    That box read SOUL.md absent: the producer is right (fail-open by design), the expectation was stale.
    Qualified: the always-on writers are asserted everywhere; the bootstrap writers exactly when the same env
    reads an identity, and absent when it reads none (the ``no-git`` case reproduces that box on Linux).

    Killing mutations, each red recorded: ``initialize_home`` without ``_ensure_default_soul_md`` -> ``[git]``
    red; ``maybe_run_boot_bootstrap`` returning before ``run_boot_bootstrap`` -> ``[git]`` red (identity read,
    no record); ``setup_logging``'s read-only guard answering read-only for every argv -> both red."""

    identity = _child_install_identity(tmp_path, no_git=no_git)
    if no_git:
        assert identity == "", "a child with no git reads no checkout identity"

    result = _run_cli(seeded_home, "sessions", "list", no_git=no_git)

    assert result.returncode == 0, result.stderr
    after = _tree(seeded_home)
    for written in _ALWAYS_WRITTEN:
        assert written in after, sorted(after)
    recorded = any(p.startswith("installs/") and p.endswith("bootstrap/default.json") for p in after)
    assert recorded is bool(identity), (identity, sorted(after))
    for written in _BOOTSTRAP_WRITTEN:
        assert (written in after) is bool(identity), (identity, sorted(after))


# -- each guard on its own: the CLI case above reaches ensure_hermes_home only through the
#    bootstrap's home steps, so a guard the bootstrap guard shadows needs its own killer.

_EXPORT_ARGV = ["hermes", "sessions", "export", "--format", "jsonl", "-"]
_WRITING_ARGV = ["hermes", "sessions", "list"]


@pytest.mark.parametrize(("argv", "writes"), [(_EXPORT_ARGV, False), (_WRITING_ARGV, True)])
def test_ensure_hermes_home_guard(tmp_path, monkeypatch, argv, writes):
    from hermes_cli import config

    home = tmp_path / "fresh-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(sys, "argv", argv)
    config.ensure_hermes_home()
    assert (home / "SOUL.md").exists() is writes


@pytest.mark.parametrize(("argv", "writes"), [(_EXPORT_ARGV, False), (_WRITING_ARGV, True)])
def test_setup_logging_guard(tmp_path, monkeypatch, argv, writes):
    import hermes_logging

    monkeypatch.setattr(sys, "argv", argv)
    log_dir = hermes_logging.setup_logging(hermes_home=tmp_path)
    assert log_dir == tmp_path / "logs"
    assert log_dir.exists() is writes


@pytest.mark.parametrize(("argv", "runs"), [(_EXPORT_ARGV, False), (_WRITING_ARGV, True)])
def test_boot_bootstrap_guard(tmp_path, monkeypatch, argv, runs):
    from hermes_cli import boot_bootstrap

    calls = []
    monkeypatch.setattr(boot_bootstrap, "run_boot_bootstrap", lambda root: calls.append(root))
    monkeypatch.setattr(sys, "argv", argv)
    boot_bootstrap.maybe_run_boot_bootstrap(tmp_path)
    assert bool(calls) is runs


@pytest.mark.parametrize(("argv", "runs"), [(_EXPORT_ARGV, False), (_WRITING_ARGV, True)])
def test_scratch_export_guard(monkeypatch, argv, runs):
    import hermes_constants

    calls = []
    monkeypatch.setattr(hermes_constants, "apply_scratch_tmp_env", lambda env: calls.append(env) or False)
    monkeypatch.setattr(sys, "argv", argv)
    assert hermes_constants.export_scratch_tmp_env() is False
    assert bool(calls) is runs
