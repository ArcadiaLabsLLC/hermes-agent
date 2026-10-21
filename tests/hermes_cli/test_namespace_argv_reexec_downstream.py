"""RT-NAMESPACE-ARGV-SURVIVES-REEXEC: hermes' own re-execs carry ``--namespace``.

``apply_cli_namespace`` strips the flag from the in-process ``sys.argv`` only; the OS command line
of the process never changes. A re-exec built from ``sys.argv`` AFTER the strip would start a child
whose argv lacks the flag (the launcher's sweeps read store identity from argv). Every re-exec on a
``hermes`` launch runs BEFORE the strip: the bootstrap's interpreter relaunch
(``hermes_bootstrap`` -> ``venv_sync.relaunch_if_needed``) and the interrupted-pull relaunch
(``_early_recovery.relaunch_after_restore``, from ``sys.orig_argv``). This pins that order.
"""

import ast
from pathlib import Path

from hermes_cli.venv_sync import relaunch_command

_MAIN = Path(__file__).resolve().parents[2] / "hermes_cli" / "main.py"


def _top_level_index(tree: ast.Module, predicate) -> int:
    for index, node in enumerate(tree.body):
        if predicate(node):
            return index
    raise AssertionError("statement not found at module level of hermes_cli/main.py")


def test_every_reexec_runs_before_the_namespace_strip():
    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))

    def _is_bootstrap_import(node):
        return isinstance(node, ast.Try) and any(
            isinstance(inner, ast.Import) and any(alias.name == "hermes_bootstrap" for alias in inner.names)
            for inner in node.body
        )

    def _is_restore_relaunch(node):
        return isinstance(node, ast.If) and "relaunch_after_restore" in ast.unparse(node)

    def _is_strip(node):
        return not isinstance(node, ast.FunctionDef) and any(
            isinstance(inner, ast.Call) and ast.unparse(inner.func) == "_apply_profile_override"
            for inner in ast.walk(node)
        )

    strip = _top_level_index(tree, _is_strip)
    assert _top_level_index(tree, _is_bootstrap_import) < strip
    assert _top_level_index(tree, _is_restore_relaunch) < strip


def test_the_interpreter_relaunch_hands_the_child_the_flag(tmp_path):
    argv = ["hermes", "harness", "serve", "--namespace", "acct-1"]
    command = relaunch_command(tmp_path / "python", tmp_path, argv, ["python", "hermes"], "hermes_cli.main")
    assert "'--namespace', 'acct-1'" in command[-1]
