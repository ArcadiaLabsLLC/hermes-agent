"""The fork's ``hermes postinstall`` handler (registered by the eternia-harness plugin).

Provisioning goes through upstream's package manager (``pm``) — the one
installer since upstream ``5e4a2a3d24`` retired ``hermes_cli.dep_ensure``.
Every install here is ``explicit=True``: a deliberate install command is the
remedy pm's lazy-install policy points at.
"""
import json
import shutil
import sys

_IS_WINDOWS = sys.platform == "win32"

#: ``hermes.postinstall/1`` dep keys -> pm package names (keys unchanged so the
#: schema stays ``/1``; the launcher reads only ``git_bash_path``).
_POSTINSTALL_PACKAGES = (
    ("node", "node"),
    ("browser", "agent-browser"),
    ("ripgrep", "ripgrep"),
    ("ffmpeg", "ffmpeg"),
)


def _pm_has(name: str) -> bool:
    import pm

    try:
        return pm.installed_package(name) is not None
    except Exception:
        return False


def _ensure_git_bash() -> "str | None":
    """The shell Hermes runs terminal commands through, provisioned by pm when absent.

    ``pm.shell.bash()`` is the one resolver (store-staged bash first, then Git for
    Windows roots honouring ``HERMES_GIT_BASH_PATH``, never the System32 / WindowsApps
    stubs). On Windows a miss asks pm for its portable Git and re-resolves; nothing is
    persisted — a store-staged bash is found by a fresh process without an env var.
    """
    import pm
    import pm.shell

    bash = pm.shell.bash()
    if bash or not _IS_WINDOWS:
        return bash
    try:
        pm.ensure("git", explicit=True)
    except (pm.InstallError, OSError) as exc:
        print(f"⚠ Git Bash could not be provisioned: {exc}")
        return None
    return pm.shell.bash()


def cmd_postinstall(args):
    """One-shot bootstrap for pip users: install non-Python deps + run setup."""
    from hermes_cli.main import _has_any_provider_configured, cmd_setup
    from hermes_cli.install_method import stamp_install_method
    import pm
    from hermes_cli.path_setup import register_hermes_command
    from hermes_constants import get_hermes_home

    stamp_install_method("pip")

    emit_json = getattr(args, "json", False)

    print("⚕ Hermes post-install bootstrap")
    print()

    # --yes / --non-interactive keep one meaning: skip the provider setup wizard.
    # Install consent is pm's policy, and explicit=True is the deliberate-install signal.
    interactive = not (getattr(args, "yes", False) or getattr(args, "non_interactive", False))
    for _key, package in _POSTINSTALL_PACKAGES:
        try:
            pm.ensure(package, explicit=True)
        except (pm.InstallError, OSError) as exc:
            print(f"⚠ {package} not installed: {exc}")

    # Provision the shell Hermes runs terminal commands through (Git Bash on
    # Windows; native bash elsewhere) so the agent never falls through to the
    # System32 WSL stub.
    git_bash_path = _ensure_git_bash()

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
            "deps": {
                **{key: _pm_has(package) for key, package in _POSTINSTALL_PACKAGES},
                "git": bool(shutil.which("git")) or _pm_has("git"),
                "git-bash": git_bash_path is not None,
            },
        }
        # MUST be the final stdout line — the launcher scans for this schema.
        print(json.dumps(summary))
