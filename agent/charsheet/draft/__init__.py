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
because it imports the class. ``CharacterDraft`` is the only entry the CLI sees:
it keeps its constructor, create/load/list, the properties, the lock and the
guards, and delegates each stage verb — same name, same signature — to one of
five objects it composes.

    agent/charsheet/_support.py  models  utc_now, the two atomic writers, slugify, safe_segment,
                                         and the ONE call-time reach into agent_runtime (Q9)
    agent/charsheet/draft/
      __init__.py    lanes    this map; re-exports CharacterDraft, the constants and the test-pinned names
      layout.py      models   SCHEMA, Stage + STAGE_ORDER + VERB_STAGES, the file names, thumb defaults;
                              characters_dir, drafts_dir, stamp_recorded_home; the spec round-trip;
                              the revision keys; path_or_none, read_palette
      migration.py   lanes    migrate_characters_home (+ _migration_entry_id)
      installed.py   stores   sprite_payload, sheet_revision, _handedness_accepted — the installed readers
      draft.py       lanes    CharacterDraft: identity, create/load/list, properties, lock, guards, delegators
      directions.py  lanes    DirectionStage: base image, turnaround, re-roll/approve directions
      rows.py        lanes    RowStage: run_rows, reroll_row, add_state
      thumbs.py      lanes    Thumbs: row_thumb, direction_thumb, _finish_thumb
      compose.py     lanes    Composer: compose (collect -> validate -> guard_slug -> write_sheet -> manifest), reopen
      status.py      lanes    StatusReport: status_payload, _item_status

    entry point                                     opens
    CharacterDraft.create / load / list_drafts      draft -> layout -> _support
    run_turnaround / reroll_direction / approve_*   draft -> directions -> layout
    run_rows / reroll_row / add_state               draft -> rows -> layout
    row_thumb / direction_thumb                     draft -> thumbs -> layout
    compose / reopen                                draft -> compose -> installed
    status_payload                                  draft -> status -> layout
    migrate_characters_home                         migration -> layout -> _support
    sprite_payload                                  installed -> layout
"""

from __future__ import annotations

from agent.charsheet._support import slugify

from . import compose, directions, draft, installed, layout, migration, rows, status, thumbs
from .compose import (
    Composer,
)
from .directions import (
    DirectionStage,
)
from .draft import (
    CharacterDraft,
)
from .installed import (
    _handedness_accepted,
    _row_json,
    sheet_revision,
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
    STAGE_ORDER,
    Stage,
    THUMBS_DIRNAME,
    VERB_STAGES,
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
from .rows import (
    RowStage,
)
from .status import (
    StatusReport,
)
from .thumbs import (
    Thumbs,
)

__layer__ = "lanes"


