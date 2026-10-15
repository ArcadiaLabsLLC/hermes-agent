"""Which checkout a Windows ``$HERMES_HOME\\bin`` launcher belongs to — fork-owned, stdlib only.

Upstream ``hermes_cli/_launchers.py::_expose_windows_user_bin`` re-stages
``$HERMES_HOME\\bin\\hermes*`` for whichever checkout ran last, with none of the ownership
guard its POSIX twin has (``_publish_conveniences`` skips an entry ``_owns_launcher`` says
belongs to another root). A lane's worktree booting under the live ``HERMES_HOME`` therefore
rebound the operator's ``hermes.exe`` onto a tree with no dependency environment, and the
operator's ``hermes`` exited 1 (runtime-queue L6.12, measured 2026-10-01).

:func:`foreign_launcher_root` is the Windows ownership read: the checkout root a published
launcher bootstraps (``sys.path.insert(0, <root>)`` in the distlib ``.exe``'s embedded
``__main__.py`` or the ``.cmd``'s base64 script), when that root is ANOTHER checkout that
still exists. The data root's own installed checkout never defers (it heals a rebound bin,
as ``ensure_install_launchers`` already lets it); a launcher naming a deleted root, or one
whose layout is unrecognized, is republished as before. Retires with the upstream PR that
gives the Windows copy the POSIX guard (w5-fh verdict (a)).
"""

from __future__ import annotations

import ast
import base64
import re
from pathlib import Path

_BOOTSTRAP = re.compile(r"^sys\.path\.insert\(0, (?P<root>'[^\n]*'|\"[^\n]*\")\)$", re.MULTILINE)
_CMD_SCRIPT = re.compile(r"b64decode\('(?P<payload>[A-Za-z0-9+/=]+)'\)")


def _script_text(target: Path) -> str | None:
    """The Python bootstrap a published launcher runs, or None for an unknown layout."""
    if target.suffix.lower() == ".exe":
        from zipfile import BadZipFile, ZipFile

        try:
            with ZipFile(target) as archive:
                return archive.read("__main__.py").decode("utf-8")
        except (OSError, BadZipFile, KeyError, UnicodeDecodeError):
            return None
    try:
        match = _CMD_SCRIPT.search(target.read_text(encoding="utf-8-sig"))
        return base64.b64decode(match["payload"]).decode("utf-8") if match else None
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def launcher_root(target: Path) -> Path | None:
    """The checkout root a published launcher puts first on ``sys.path``, else None."""
    script = _script_text(target)
    match = _BOOTSTRAP.search(script) if script else None
    if match is None:
        return None
    try:
        return Path(ast.literal_eval(match["root"]))
    except (ValueError, SyntaxError):
        return None


def _is_home_install(root: Path) -> bool:
    """The data root's own installed checkout: ``<home>/hermes-agent`` with ``<home>/tools``.

    The same predicate ``ensure_install_launchers`` uses for its always-republish owner."""
    from hermes_constants import get_default_hermes_root
    from pm.environments import owning_home_root, store_root

    home = get_default_hermes_root().resolve()
    return (root.parent == home and store_root(root).resolve() == (home / "tools").resolve()
            and owning_home_root(root) is None)


def foreign_launcher_root(root: Path, directory: Path, names) -> Path | None:
    """Another live checkout that owns a launcher in ``directory``, else None (publish)."""
    root = Path(root).resolve()
    if _is_home_install(root):
        return None
    for name in names:
        for suffix in (".exe", ".cmd"):
            target = Path(directory) / f"{name}{suffix}"
            if not target.is_file():
                continue
            other = launcher_root(target)
            if other is None or not other.is_dir():
                continue
            try:
                if other.resolve() != root:
                    return other
            except OSError:
                continue
    return None
