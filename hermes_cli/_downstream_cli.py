"""The fork's ``hermes postinstall`` handler (registered by the eternia-harness plugin)."""
import json
import sys

def cmd_postinstall(args):
    """One-shot bootstrap for pip users: install non-Python deps + run setup."""
    from hermes_cli.main import _has_any_provider_configured, cmd_setup
    from hermes_cli.install_method import stamp_install_method
    from hermes_cli.dep_ensure import ensure_dependency, ensure_git_bash, _DEP_CHECKS
    from hermes_cli.path_setup import register_hermes_command
    from hermes_constants import get_hermes_home

    stamp_install_method("pip")

    emit_json = getattr(args, "json", False)

    print("⚕ Hermes post-install bootstrap")
    print()

    interactive = not (getattr(args, "yes", False) or getattr(args, "non_interactive", False))
    for dep in ("node", "browser", "ripgrep", "ffmpeg"):
        ensure_dependency(dep, interactive=interactive)

    # Provision the shell Hermes runs terminal commands through (Git Bash on
    # Windows; native bash elsewhere) and persist HERMES_GIT_BASH_PATH so the
    # agent never falls through to the System32 WSL stub.
    git_bash_path = ensure_git_bash(interactive=interactive)

    # Put `hermes` on PATH via a stable wrapper shim. The home baked into it is
    # THIS install's canonical resolution and nothing else — the shim outlives
    # the run and repeats whatever it was handed for the life of the install.
    path_result = register_hermes_command(get_hermes_home())

    # Say what happened. The whole result used to be reachable only inside the
    # `--json` branch, so a human running `hermes postinstall` was told nothing
    # at all — neither a refusal nor the "add this dir to your PATH" guidance.
    if path_result.error:
        print()
        print(f"⚠ PATH shim not written [{path_result.error}]: {path_result.note}")
    elif path_result.note:
        print()
        print(f"⚠ {path_result.note}")

    if not _has_any_provider_configured():
        print()
        if interactive:
            cmd_setup(args)
        else:
            print("✓ Post-install complete. Provider setup skipped for non-interactive install.")
    else:
        print()
        print("✓ Post-install complete.")

    if emit_json:
        note = path_result.note
        if git_bash_path is None and sys.platform == "win32":
            gb_note = (
                "Git Bash not found. Install Git for Windows "
                "(https://git-scm.com/download/win) or set HERMES_GIT_BASH_PATH."
            )
            note = f"{gb_note} {note}".strip() if note else gb_note
        summary = {
            "schema": "hermes.postinstall/1",
            "git_bash_path": git_bash_path,
            "shim_path": path_result.shim_path,
            "path_dir": path_result.path_dir,
            "path_registered": path_result.path_registered,
            # Additive to `hermes.postinstall/1`: the refusal's machine-readable
            # code beside the prose, so the installer can branch on it without
            # matching a sentence. `None` on a run that wrote a shim.
            "error": path_result.error,
            "note": note,
            "deps": {name: bool(check()) for name, check in _DEP_CHECKS.items()},
        }
        # MUST be the final stdout line — the launcher scans for this schema.
        print(json.dumps(summary))
