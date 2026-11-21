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


def checkout_launcher(name: str, root: Path, local: Path, kept: Path | None) -> Path | None:
    """The checkout launcher ``ensure_install_launchers`` reports for *name*, or None to let it stage one.

    Only the checkout's own store interpreter publishes the checkout's ``.hermes/bin``
    (RT-FU-A-QA-COPY-REWRITES-THE-OWNERS-CHECKOUT-LAUNCHERS). A home that BORROWS the checkout
    (``pm.environments.owning_home_root`` names another data root: a Stage C QA copy, a test's or a
    task's ``HERMES_HOME``) used to stage a missing launcher on its own interpreter, and the #123238
    keep then held that binding for good: the owner's ``hermes`` ran the QA tree's interpreter, and
    exited before Hermes started once that tree was deleted. Under a borrower the launcher is
    published on the OWNING root's store interpreter (``<owner>/tools``), which also re-binds one an
    earlier borrower left; the borrower's own commands go to its own bin (the caller's ``out_dir``).
    A home that owns the checkout, or a root no owner is known for, keeps upstream's rule: a kept
    launcher is re-minted on the interpreter it already names (:func:`refresh_kept_launcher`).
    Edge, documented: an owner whose store records no interpreter falls back to that rule too.
    """
    from pm.environments import owning_home_root

    try:
        owner = owning_home_root(root)
    except Exception:  # health: allow BLE001 -- no owner read: upstream's rule, as before this seam
        owner = None
    if owner is not None:
        published = _publish_on_owner_store(name, root, local, Path(owner))
        if published is not None:
            return published
    return None if kept is None else refresh_kept_launcher(name, root, local, kept)


def _publish_on_owner_store(name: str, root: Path, local: Path, owner: Path) -> Path | None:
    """*name* in the checkout's bin bound to *owner*'s store interpreter; None when it has none."""
    from hermes_cli import _launchers

    # The checkout's publication store is the owning root's ``tools/`` (``pm.environments.store_root``:
    # a source stamp names no store, so the owner's is used) -- read through upstream's public door, and
    # taken only when it IS that store: a tree whose stamp names another store, or none at all, would
    # otherwise hand back the borrower's interpreter.
    python = _launchers.resolve_store_python(root, publication=True)
    if python is None or not _is_within(python, owner / "tools"):
        return None
    try:
        minted = _launchers.mint_launcher(name, root, local, python, None)
    except Exception:  # health: allow BLE001 -- never publish the borrower's interpreter over a failed mint
        return None
    if minted is not None and minted.suffix.lower() == ".cmd":
        # cmd.exe resolves the .exe first: a borrower's .exe must not shadow the owner's command.
        try:
            (local / f"{name}.exe").unlink(missing_ok=True)
        except OSError:
            return None
    return minted


def _is_within(path: Path, directory: Path) -> bool:
    try:
        return path.resolve().is_relative_to(directory.resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def refresh_kept_launcher(name: str, root: Path, local: Path, kept: Path) -> Path:
    """*kept* re-minted on its own interpreter with the current bootstrap; *kept* when it cannot be."""
    from hermes_cli import _launchers

    python = _launchers._launcher_python(kept)
    if python is None or not python.is_file():
        return kept
    try:
        if kept.suffix.lower() == ".cmd":
            # A kept .cmd is refreshed AS a .cmd. mint_launcher prefers distlib's .exe on Windows,
            # which published a second command beside the kept one and left its stale script on
            # disk (Windows 2026-11-10: test_dead_exe_never_shadows_kept_cmd red).
            minted = _remint_cmd(name, root, local, python)
        else:
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


def _remint_cmd(name: str, root: Path, local: Path, python: Path) -> Path | None:
    """The ``.cmd`` mint_launcher writes without distlib: *python*, today's script."""
    import base64

    from hermes_cli import _launchers

    script = _launchers._launcher_script(name, root, None)
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    body = f'@echo off\r\n"{python}" -I -c "import base64; exec(base64.b64decode(\'{encoded}\'))" %*\r\n'
    return _replace_file(local / f"{name}.cmd", body)


def _replace_file(target: Path, body: str) -> Path | None:
    """*target* holding *body*, swapped in whole so a starting process never reads half a launcher."""
    import contextlib
    import os

    staged = target.with_name(f"{target.name}.refresh.{os.getpid()}")
    try:
        staged.write_text(body, encoding="utf-8")
        os.replace(staged, target)
    except OSError:
        with contextlib.suppress(OSError):
            staged.unlink()
        return None
    return target
