"""A kept shared launcher keeps its interpreter but runs the CURRENT bootstrap — fork-owned.

Upstream ``hermes_cli/_launchers.py::_kept_shared_launcher`` (#123238) keeps a checkout's
``.hermes/bin`` launcher that execs a live interpreter outside this root's store, so a launch
under one data root never repoints the shared command at its own interpreter. It kept the
whole FILE, so the embedded bootstrap script froze at whatever generation wrote it: on the
owner's Windows box (2026-11-06) an October ``hermes.cmd`` bound to a QA sandbox's interpreter
survived the November source update with a bootstrap from before the CLI entry-point contract,
so ``-p <profile>`` was not consumed and gateway recovery picked the sticky profile instead of
the host default (RT-PUBLISHED-LAUNCHER-OBSOLETE-BOOTSTRAP).

:func:`refresh_kept_launcher` re-mints the kept launcher on the interpreter it ALREADY names
with today's script. ``mint_launcher`` writes only on a difference (the ``.exe`` compares
loader, shebang and ``__main__.py``; the ``.cmd`` and POSIX wrappers compare bytes), so a
current launcher is untouched and the binding is never moved. An unreadable interpreter or a
failed mint keeps the file as upstream did.
"""

from __future__ import annotations

from pathlib import Path


def refresh_kept_launcher(name: str, root: Path, local: Path, kept: Path) -> Path:
    """*kept* re-minted on its own interpreter with the current bootstrap; *kept* when it cannot be."""
    from hermes_cli import _launchers

    python = _launchers._launcher_python(kept)
    if python is None or not python.is_file():
        return kept
    try:
        minted = _launchers.mint_launcher(name, root, local, python, None)
    except Exception:  # health: allow BLE001 -- a kept launcher still runs; never fail publication over a refresh
        return kept
    if minted is None:
        return kept
    if minted.suffix.lower() == ".cmd":
        # cmd.exe resolves the .exe first: a stale one must not shadow the refreshed command
        # (stage_launcher drops the same shadow).
        try:
            (local / f"{name}.exe").unlink(missing_ok=True)
        except OSError:
            return kept
    return minted
