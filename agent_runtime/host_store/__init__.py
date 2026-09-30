"""The host secure-store seam: credentials and chat history on a phone (embedded-hermes Stage 2).

When the embedding host (the Launcher's in-process wire on a phone) binds a store,
every credential store Hermes writes (the census:
``docs/downstream/credential-store-census-2026-09-28.md``) lives in the host's secure
store through three callbacks. Chat history is upstream's own files: on a phone the
host puts the OS's file protection and a no-cloud-backup mark on the history folder
through a fourth callback (``protect_history_dir``), which the embedded serve calls
before it starts. Unbound — every desktop Hermes — nothing here runs and every store
is byte-for-byte upstream's.

* :mod:`.binding` — the callback contract and the one process-wide binding.
* :mod:`.secret_files` — path-keyed secret files (the upstream seams call it).
* :mod:`.desktop` / :mod:`.desktop_binding` — the bundled desktop's OS secure store.
* :mod:`.fake` — an in-memory host store for CI.
"""

from __future__ import annotations

__layer__ = "models"
