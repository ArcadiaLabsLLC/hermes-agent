"""The launch's relaunch step — fork-owned, beside upstream's ``hermes_cli/venv_sync.py``.

``hermes_bootstrap`` runs :func:`relaunch_if_needed` before dependency activation: finish a pending
source update and re-enter the managed interpreter (upstream's inline block, kept out of the
bootstrap so the module every embedder imports starts no process itself), then the fork's
interpreter-ABI re-entry. It lived in ``venv_sync`` as PR #129413's shape until 2026-11-10; it is a
fork module now so ``venv_sync.py`` is upstream's bytes (FH-FOOTPRINT-VENV-SYNC-RELAUNCH). A bundle
that ships no relaunch machinery (the phone profile switches this module and ``venv_sync`` off) and a
boot fixture that copies only upstream's boot files both fall back, in ``hermes_bootstrap``, to
recovery alone.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from hermes_cli.venv_sync import prepare_launch, relaunch_command


def _relaunch(python: Path, root: Path, exit_type: type[SystemExit]) -> None:
    """Re-enter this invocation under ``python``; never returns."""
    import sys

    main_spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    command = relaunch_command(python, root, sys.argv, sys.orig_argv, getattr(main_spec, "name", None))
    if os.name == "nt":
        raise exit_type(subprocess.call(command))
    os.execv(str(python), command)


def relaunch_if_needed(root: Path, *, recover, exit_type: type[SystemExit]) -> None:
    """The launch's relaunch step, run by ``hermes_bootstrap`` before dependency activation.

    Finishes a pending source update and re-enters the managed interpreter when this one is
    not it (``prepare_launch``); runs ``recover(root)``; then re-enters the generation's own
    interpreter when the selected generation was built for another Python ABI. A relaunch
    raises ``exit_type`` carrying the child's status (Windows) or replaces this process.

    A failure to prepare the launch degrades to the previous dependencies with a warning;
    ``recover`` / ABI failures propagate to the caller, which owns the repair remedy.
    Living here, not at ``hermes_bootstrap`` module level, keeps the process-starting code
    out of a module every embedder imports.
    """
    import sys

    from hermes_cli._parser import command_argv
    from pm.environments import install_state_permission_message

    try:
        launch_python = prepare_launch(root, sys.argv[1:])
        if launch_python is not None:
            _relaunch(launch_python, root, exit_type)
    except Exception as exc:
        if isinstance(exc, PermissionError) and (message := install_state_permission_message(root, exc)):
            print(f"hermes: {message}", file=sys.stderr)
            raise SystemExit(1) from None
        # Degrade, never brick the CLI: the previous dependency generation is still selected
        # (a failed sync commits nothing), so an offline or half-finished update leaves a
        # usable Hermes plus a warning. Activation after this is the real gate — a tree whose
        # dependencies cannot load still exits with the repair remedy.
        print(f"hermes: source-update completion failed: {exc}; "
              "running with the previous dependencies — run `hermes update` to finish it",
              file=sys.stderr)
    recover(root)
    # Fork seam: a generation built for another Python loses its compiled modules on this
    # interpreter (openai → pydantic_core); re-enter the generation's own. `pm` keeps its
    # launch contract, as in prepare_launch. See hermes_cli/interpreter_abi.py.
    # A tree without the fork's probe (upstream's boot fixtures copy only upstream's
    # boot files) boots as upstream does; any other import failure still raises.
    try:
        from hermes_cli.interpreter_abi import generation_interpreter_for_mismatch
    except ModuleNotFoundError as abi_exc:
        if abi_exc.name != "hermes_cli.interpreter_abi":
            raise
        return
    if command_argv(sys.argv[1:])[:1] != ["pm"]:
        abi_python = generation_interpreter_for_mismatch(root)
        if abi_python is not None:
            _relaunch(abi_python, root, exit_type)
