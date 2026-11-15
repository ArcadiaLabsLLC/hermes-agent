"""Fork-owned: an agent's terminal runs the ``hermes`` of the code that is serving it.

Rows RT-AGENT-TERMINAL-HERMES-RUNS-ANOTHER-INSTALL and
RT-TERMINAL-PAYLOAD-HERMES-LOSES-TO-THE-LOGIN-PROFILE (owner 2026-11-15: "ok thats fine 4 lines ,
dont forget to add to ledger"). Ledger row ``tools/environments/local.py``.

Two facts made a terminal's ``hermes`` another install's:

* ``_resolve_hermes_bin_dir`` (upstream) pinned only a sealed payload's launcher dir. A
  checkout's own published launchers (``<code root>/.hermes/bin``, the dir pm's activation
  already puts first on the serve's PATH) were taken from ``shutil.which`` and only prepended
  when missing, so nothing kept them first.
* The terminal runs ``bash -lic``: the user's login profile (``~/.profile`` prepending
  ``~/.local/bin``) runs AFTER the spawn env is set, so even a pinned dir at the front of the
  spawn env lost to the machine install's ``~/.local/bin/hermes``. Upstream's login prelude
  (``_append_dropped_path_entries``) only re-APPENDS dropped dirs.

The seam is two calls: :func:`pinned_launcher_dir` widens the pinned dir from "a payload's" to
"a payload's, else this checkout's own", and :func:`front_move_line` is a shell line the login
prelude runs after the profile, putting the pinned dir first again. Pinned by
``tests/tools/test_terminal_pinned_hermes.py``.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

__layer__ = "policy"
__all__ = ["front_move_line", "pinned_launcher_dir"]

# The checkout-launcher pin. The test suite turns it off (``tests/_downstream/terminal_pinned_hermes_off.py``):
# the runner publishes the checkout's own launchers, which are the test runner's, not a serve's.
PIN_OWN_LAUNCHERS = True


def _holds_hermes(directory: Path) -> bool:
    names = ("hermes.exe", "hermes.cmd", "hermes") if os.name == "nt" else ("hermes",)
    return any((directory / name).is_file() for name in names)


def pinned_launcher_dir(payload_dir: Path | None, code_root: Path) -> Path | None:
    """The launcher dir an agent's terminal must reach first, or ``None``.

    A sealed payload's own launcher dir when there is one (upstream's rule, unchanged), else the
    running checkout's published ``.hermes/bin`` when it holds a ``hermes``. ``None`` leaves
    upstream's ``which`` order in charge (a bare dev checkout with no published launchers).
    """
    if payload_dir is not None and payload_dir.is_dir():
        return payload_dir
    if not PIN_OWN_LAUNCHERS:
        return None
    own = Path(code_root) / ".hermes" / "bin"
    return own if own.is_dir() and _holds_hermes(own) else None


def front_move_line(bin_dir: str | None, pinned: bool) -> str:
    """A shell line, run after the login profile, that puts *bin_dir* first on ``PATH``.

    Empty unless the dir is pinned (a payload's or the checkout's own): an unpinned ``which``
    answer keeps upstream's rule that the login PATH's order wins. The line runs once per login
    shell (each spawn, and the env snapshot's one login), so a later copy of the dir in ``PATH``
    is harmless -- the first entry wins and nothing accumulates.
    """
    if not (pinned and bin_dir and os.path.isabs(bin_dir)):
        return ""
    return f"\nPATH={shlex.quote(bin_dir)}:\"$PATH\"; export PATH"
