"""Staged character drafts — the QA state machine, the install, the payload.

A draft is a directory under ``<hermes_root>/shared/characters/.drafts/<id>/``
holding ``draft.json`` (schema 1), the base identity image, an
:class:`~agent.charsheet.revisions.ImageRevisionStore` of every attempt, and the
accepted row strips. Installing writes
``<hermes_root>/shared/characters/<slug>/{character.json, sheet.webp}``.

**The library is install-wide, not profile-scoped.** Every persona profile under
one hermes root resolves the SAME directory (see :func:`characters_dir`), so a
draft id names a draft for the whole install and a turn that resolved a home
nobody selected still reads the library the operator meant.

**The stage machine is the operator's QA order, and it is enforced.**
``turnaround`` → ``rows`` → ``composed``: the cardinal directions are approved
before any animation is generated, because every animation row is grounded on an
approved direction reference and re-rolling rows after changing a reference would
waste the expensive half of the flow. Every stage verb refuses an out-of-order
call with a :class:`ValueError` naming the current stage and what it requires.

**What is auto-approved, and why.** Direction references are the identity gate,
so they are proposed and wait for a human. Row strips are proposed *and*
immediately approved: their failure mode is geometric (touching poses, merged
frames) and that is already rejected mechanically before a strip is accepted
(:func:`agent.charsheet.pipeline.generate_row_strip`), so what remains is a
judgement call — "that walk looks wrong" — which the operator makes by looking at
the status payload and re-rolling. Making 10+ rows individually approvable would
add a click per row without adding a decision. A re-rolled row is auto-approved
for the same reason; the gate is visual, and a re-roll always replaces what the
sheet will use.

**Concurrency.** Every JSON write is tmp + :func:`os.replace` (the revision
store's discipline), so a reader sees one whole state or the other. That is
atomicity per FILE and says nothing about two WRITERS, so every verb that
generates holds a per-draft advisory lock for its whole run
(:meth:`CharacterDraft.generation_lock`, :mod:`agent.charsheet.draft_lock`) and
a second writer is refused :class:`~agent.charsheet.errors.DraftBusy`. It is
built inside this package rather than on ``agent_runtime.locks`` because
``agent_runtime`` is not in the shipped wheel — the packaging boundary
:mod:`agent.charsheet` opens with — and the lock module records the rest of that
argument.

The verbs that do NOT generate (the approvals, ``add_state``, ``reopen``,
``status``, ``list``) stay lock-free and last-writer-wins per item: each is one
small write an operator makes by hand, and refusing a click because a batch is
running would cost more than it protects.

Package map (lane B1, sheet ``god-file-layout-sheets/draft.md`` §1). Layers point
down (models <- policy <- stores <- lanes <- wiring); this map is ``lanes``
because it imports the class. ``CharacterDraft`` is moved WHOLE for one commit
(ruling Q8) — the only module in the batch over the 500 cap, and only here.

    agent/charsheet/_support.py  models  utc_now, the two atomic writers, slugify, safe_segment
    agent/charsheet/draft/
      __init__.py    lanes    this map; re-exports CharacterDraft, the constants and the test-pinned names
      layout.py      models   SCHEMA, STAGES, the file names, thumb defaults; characters_dir, drafts_dir,
                              stamp_recorded_home; the spec round-trip; the revision keys; path_or_none, read_palette
      migration.py   lanes    migrate_characters_home (+ _migration_entry_id)
      installed.py   stores   sprite_payload, the sheet revision, _handedness_accepted — the installed readers
      draft.py       lanes    CharacterDraft (whole, this commit)

    entry point                                     opens
    CharacterDraft.*                                draft -> layout -> _support
    migrate_characters_home                         migration -> layout -> _support
    sprite_payload                                  installed -> layout
"""

from __future__ import annotations

from agent.charsheet._support import slugify

from . import draft, installed, layout, migration
from .draft import (
    CharacterDraft,
)
from .installed import (
    _handedness_accepted,
    _row_json,
    sprite_payload,
)
from .layout import (
    DEFAULT_THUMB_FRAME,
    DEFAULT_THUMB_SCALE,
    DRAFTS_DIRNAME,
    DRAFT_FILENAME,
    MANIFEST_FILENAME,
    PALETTE_FILENAME,
    REVISIONS_DIRNAME,
    SCHEMA,
    SHEET_FILENAME,
    STAGES,
    THUMBS_DIRNAME,
    characters_dir,
    drafts_dir,
    path_or_none,
    read_palette,
    row_item,
    spec_from_dict,
    spec_to_dict,
    stamp_recorded_home,
    turnaround_item,
)
from .migration import (
    _migration_entry_id,
    migrate_characters_home,
)

__layer__ = "lanes"


