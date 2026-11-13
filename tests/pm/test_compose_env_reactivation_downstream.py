"""Repeated source-update activation must not grow the managed tool search path."""
import os

from pm.package import compose_env


def test_reactivation_preserves_tool_precedence_and_user_path():
    diffs = [{"PATH": ["managed-node"]}, {"PATH": ["managed-pnpm", "managed-node"]}]
    inherited = os.pathsep.join(["user-first", "managed-node", "", "user-last", "user-first"])
    original = {"PATH": inherited, "UNCHANGED": "value"}
    env = compose_env(diffs, original)
    for _ in range(20):
        env = compose_env(diffs, env)
    assert env == {
        "PATH": os.pathsep.join(["managed-pnpm", "managed-node", "user-first", "", "user-last", "user-first"]),
        "UNCHANGED": "value",
    }
    assert original["PATH"] == inherited


def test_reactivation_preserves_existing_path_key_spelling():
    env = compose_env([{"PATH": ["node"]}], {"Path": os.pathsep.join(["user", "node"])})
    assert env == {"Path": os.pathsep.join(["node", "user"])}
    assert compose_env([{"PATH": ["node"]}], env) == env


def test_windows_reactivation_matches_path_case_and_slashes(monkeypatch):
    import ntpath

    monkeypatch.setattr(os.path, "normcase", ntpath.normcase)
    monkeypatch.setattr(os, "pathsep", ";")
    env = compose_env([{"PATH": ["C:/Tools/Node"]}], {
        "PATH": os.pathsep.join([r"c:\tools\node", "user"]),
    })
    assert env["PATH"] == os.pathsep.join(["C:/Tools/Node", "user"])


def test_long_inherited_path_does_not_grow_on_reactivation():
    inherited = os.pathsep.join(f"user-{i}-" + "x" * 100 for i in range(60))
    diffs = [{"PATH": ["managed-node-" + "n" * 100, "managed-pnpm-" + "p" * 100]}]
    first = compose_env(diffs, {"PATH": inherited})
    env = first
    for _ in range(30):
        env = compose_env(diffs, env)
    assert env == first
    assert len(env["PATH"]) < 8191


def test_dependency_activation_keeps_launcher_path_stable(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys
    from pm import environments

    root = tmp_path / "repo"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    state = environments.install_state_dir(root)
    selected = state / "environments" / "selected" / "venv"
    environments.site_packages(selected).mkdir(parents=True)
    (selected / "pyvenv.cfg").write_text("home = test", encoding="utf-8")
    venv_bin = environments.venv_bin_dir(selected)
    venv_bin.mkdir(parents=True)
    checkout_bin = root / ".hermes" / "bin"
    checkout_bin.mkdir(parents=True)
    (state / "facts.json").write_text(json.dumps({"packages": {
        "venv": {"environment": str(selected)},
    }}), encoding="utf-8")
    code = (
        "import os, sys, json; from pathlib import Path; "
        "from pm.environments import activate_dependencies; "
        "root = Path(sys.argv[1]); activate_dependencies(root); first = os.environ['PATH']; "
        "[activate_dependencies(root) for _ in range(20)]; "
        "print(json.dumps([first, os.environ['PATH']]))"
    )
    result = subprocess.run([sys.executable, "-c", code, str(root)],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    first, repeated = json.loads(result.stdout)
    assert repeated == first
    assert repeated.split(os.pathsep)[:2] == [str(checkout_bin), str(venv_bin)]
