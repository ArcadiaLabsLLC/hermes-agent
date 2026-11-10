from pathlib import Path

from scripts.upstream_sync_gate import build_gate_commands

import pytest

pytestmark = pytest.mark.gate


def test_gate_commands_include_required_harness_lanes():
    commands = build_gate_commands(
        repo_root=Path("repo"),
        launcher_root=Path("launcher"),
        include_launcher=False,
    )

    assert commands[0].argv[1:] == ["scripts/run_tests_bundled.sh", "tests"]
    assert "pytest" not in commands[0].argv

    assert [command.name for command in commands] == [
        "fork_landing_gate",
        "harness_no_model_verify",
    ]


def test_no_lane_runs_a_whole_directory_through_the_per_file_runner():
    """ADR 0016: nothing runs a whole tree; scripts/run_tests.sh is the one-file authority.

    Killing mutation (2026-11-10, FH-SYNC-GATE-STALE-SMOKE-AND-DIRS): restore the
    ``scripts/run_tests.sh tests/agent_runtime`` lane -> red."""
    for command in build_gate_commands(repo_root=Path("repo"), launcher_root=Path("launcher"),
                                       include_launcher=True, simulate_broken_seam=True):
        if "scripts/run_tests.sh" in command.argv:
            paths = command.argv[command.argv.index("scripts/run_tests.sh") + 1:]
            assert all(path.endswith(".py") for path in paths if not path.startswith("-")), command


def test_the_no_model_lane_names_a_harness_command_that_exists_and_runs_in_a_scratch_home():
    """The lane's harness subcommand and options are in the committed CLI contract.

    Killing mutation (2026-11-10, FH-SYNC-GATE-STALE-SMOKE-AND-DIRS): put back
    ``harness smoke --json --no-model`` -> red (no such command; it exited 2 on main 0338812f8b)."""
    import json

    contract = json.loads((Path(__file__).resolve().parents[2] / "tests/fixtures/hermes_cli_contract.json")
                          .read_text(encoding="utf-8"))["commands"]
    (lane,) = [c for c in build_gate_commands(repo_root=Path("repo"), launcher_root=Path("launcher"),
                                              include_launcher=False) if c.name == "harness_no_model_verify"]
    argv = lane.argv[lane.argv.index("hermes_cli.main") + 1:]
    words = [a for a in argv if not a.startswith("-")]
    path, options = " ".join(words[:2]), {a for a in argv if a.startswith("-")}
    assert path in contract, path
    assert options <= set(contract[path]["options"]), options - set(contract[path]["options"])
    assert lane.isolated_home


def test_gate_commands_add_launcher_when_agent_seam_requires_it():
    commands = build_gate_commands(
        repo_root=Path("repo"),
        launcher_root=Path("launcher"),
        include_launcher=True,
    )

    assert commands[-1].name == "launcher_mission_control"


def test_rehearsal_broken_seam_runs_before_expensive_gates():
    commands = build_gate_commands(
        repo_root=Path("repo"),
        launcher_root=Path("launcher"),
        include_launcher=False,
        simulate_broken_seam=True,
    )

    assert commands[0].name == "rehearsal_broken_seam"
