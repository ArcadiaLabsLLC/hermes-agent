"""Fork-owned: print ``pm.environments``' activation exports as UTF-8 (fork-hygiene F34).

Ledger row ``pm/environments.py``: ``main`` calls :func:`utf8_stdout` before it prints. The
readers (``activate``, ``scripts/run-in-hermes-env``) evaluate bytes, and a cp1252 console (Git
Bash on Windows) cannot encode a value such as a non-ANSI path, so ``print`` died with
``UnicodeEncodeError`` before a single export was written and the runner reported a missing
environment instead. Imported inside ``main`` only, so a boot tree that copies
``pm/environments.py`` alone still imports it.
"""

from __future__ import annotations

import sys

__all__ = ["utf8_stdout"]


def utf8_stdout() -> None:
    """Emit stdout as UTF-8 whatever the console codec is."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="strict")
