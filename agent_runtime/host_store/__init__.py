"""The host secure-store seam: credentials and chat history on a phone (embedded-hermes Stage 2).

When the embedding host (the Launcher's in-process wire on a phone) binds a store,
every credential store Hermes writes (the census:
``docs/downstream/credential-store-census-2026-09-28.md``) lives in the host's secure
store through three callbacks, and the chat history (state DB, its journal, the FTS
index, transcripts) is encrypted at rest with a key the host hands over through a
fourth. Unbound — every desktop Hermes — nothing here runs and every store is
byte-for-byte upstream's.

* :mod:`.binding` — the callback contract and the one process-wide binding.
* :mod:`.secret_files` — path-keyed secret files (the upstream seams call it).
* :mod:`.envelope` — the at-rest cipher (stdlib only).
* :mod:`.history` — encrypted history files and the session store's class seam.
* :mod:`.session_db` — the one session store over an encrypted image.
* :mod:`.log_records` — file logs as encrypted records.
* :mod:`.fake` — an in-memory host store for CI.
"""

from __future__ import annotations

__layer__ = "models"
