"""The artifact families: ``pets`` and ``characters``.

One ``add_<family>(subs)`` per ``hermes harness`` family, in the order the
contract fixture lists them; ``parser.PARSER_FAMILIES`` is the only reader.
"""

from __future__ import annotations

from hermes_cli.harness_parts.characters.auto import _CHARACTERS_AUTO_STEPS, _cmd_characters_auto
from hermes_cli.harness_parts.characters.commands import (
    _cmd_characters_add_state,
    _cmd_characters_backfill_home,
    _cmd_characters_base,
    _cmd_characters_list,
    _cmd_characters_migrate_home,
    _cmd_characters_payload_contract,
    _cmd_characters_reopen,
    _cmd_characters_sprite,
    _cmd_characters_start,
    _cmd_characters_status,
    _cmd_characters_thumb,
)
from hermes_cli.harness_parts.characters.steps import (
    _cmd_characters_approve_direction,
    _cmd_characters_compose,
    _cmd_characters_reroll_direction,
    _cmd_characters_reroll_row,
    _cmd_characters_rows,
    _cmd_characters_turnaround,
)
from hermes_cli.harness_parts.pets_commands import (
    _cmd_pets_gallery,
    _cmd_pets_install,
    _cmd_pets_sprite,
    _cmd_pets_thumb,
)

__layer__ = "wiring"
__all__ = [
    "add_characters",
    "add_pets",
]


def add_pets(subs) -> None:
    """``hermes harness pets``."""
    pets = subs.add_parser("pets", help="Mission Control Petdex bridge")
    pets_subs = pets.add_subparsers(dest="pets_command", required=True)
    pets_gallery = pets_subs.add_parser("gallery", help="List Petdex pets for Launcher")
    pets_gallery.add_argument("--local-only", action="store_true", help="Only include installed pets; skip the remote manifest")
    pets_gallery.add_argument("--limit", type=int, default=0, help="Maximum remote rows; 0 = all")
    pets_gallery.add_argument("--query", default="", help="Filter by slug/display name substring")
    pets_gallery.add_argument("--json", action="store_true")
    pets_gallery.set_defaults(func=_cmd_pets_gallery)
    pets_install = pets_subs.add_parser("install", help="Install a Petdex pet by slug")
    pets_install.add_argument("slug")
    pets_install.add_argument("--force", action="store_true")
    pets_install.add_argument("--json", action="store_true")
    pets_install.set_defaults(func=_cmd_pets_install)
    pets_sprite = pets_subs.add_parser("sprite", help="Return an installed pet spritesheet payload")
    pets_sprite.add_argument("slug")
    pets_sprite.add_argument("--no-sheet", dest="no_sheet", action="store_true", help="Metadata only: drop `spritesheetBase64` and carry `sheet`, the absolute path, in its place. `spritesheetRevision` and every geometry/taxonomy key are unchanged. Mirrors `characters sprite --no-sheet`. The default is byte-identical to what it always was")
    pets_sprite.add_argument("--json", action="store_true")
    pets_sprite.set_defaults(func=_cmd_pets_sprite)
    pets_thumb = pets_subs.add_parser("thumb", help="Return a Petdex pet thumbnail")
    pets_thumb.add_argument("slug")
    pets_thumb.add_argument("--url", default="", help="Optional Petdex spritesheet URL for non-installed gallery pets")
    pets_thumb.add_argument("--json", action="store_true")
    pets_thumb.set_defaults(func=_cmd_pets_thumb)


def add_characters(subs) -> None:
    """``hermes harness characters``."""
    # Character sheets — the QA bridge for `agent.charsheet`. Deliberately a
    # sibling of `pets`, not an extension of it: character sheets carry their row
    # taxonomy as data and must never enter a pet read path (which infers the
    # taxonomy from sheet height and would misread a 16-row sheet as a 9-row pet).
    # Every verb here is a thin veneer over one CharacterDraft method; the stage
    # machine, the pixels and the revision store all live in agent/charsheet/.
    characters = subs.add_parser("characters", help="Mission Control character-sheet bridge (8-way sheets + QA)")
    characters_subs = characters.add_subparsers(dest="characters_command", required=True)

    characters_start = characters_subs.add_parser("start", help="Create a character draft at stage 'turnaround' (offline; generates nothing)")
    characters_start.add_argument("--concept", required=True, help="What to draw, e.g. 'a tall knight in green enamel armour'")
    characters_start.add_argument("--slug", default="", help="Install slug; defaults to a slugified display name")
    characters_start.add_argument("--display-name", dest="display_name", default="", help="Human name; defaults to the concept")
    characters_start.add_argument("--style", default="auto", help="Art-style hint passed to the prompts")
    characters_start.add_argument("--states", default="", help="Animation states as 'idle:6,walk:8[,cheer:5:fixed]'; default = the CHAR8 states")
    characters_start.add_argument("--directions", default="8", help="Direction scheme: 8 (five authored, three mirrored) or 4")
    characters_start.add_argument("--base-image", dest="base_image", default="", help="Identity-anchor image; copied into the draft")
    characters_start.add_argument("--authored-by", dest="authored_by", default="", help="Persona driving this authoring run, recorded as provenance; nothing scopes where the draft lives — the character library is install-wide at <hermes_root>/shared/characters, one directory for every persona and profile — but it is what lets a later reader check a resume is opening under the profile that authored it")
    characters_start.add_argument("--json", action="store_true")
    characters_start.set_defaults(func=_cmd_characters_start)
    characters_list = characters_subs.add_parser("list", help="List character drafts and installed characters")
    characters_list.add_argument("--json", action="store_true")
    characters_list.set_defaults(func=_cmd_characters_list)
    characters_backfill_home = characters_subs.add_parser("backfill-home", help="Record `hermes_home` on library drafts that carry no home, and on no others. The field is provenance of the authoring RUN, not an address — the library is install-wide, so this stamps the home THIS run resolved onto a draft that arrived without one (restored from quarantine, hand-copied in); `migrate-home` stamps the legacy source home instead, which is the case that had a better answer available. Explicit and receipted on purpose: a draft that already states a home keeps it, and the write leaves `updated` and every other key exactly as it found them, because the drafts this reaches are dormant exhibits whose timeline is evidence. Idempotent — a second run stamps nothing")
    characters_backfill_home.add_argument("--json", action="store_true")
    characters_backfill_home.set_defaults(func=_cmd_characters_backfill_home)
    characters_migrate_home = characters_subs.add_parser("migrate-home", help="Move THIS home's legacy `<HERMES_HOME>/characters` store into the install-wide library at `<hermes_root>/shared/characters`. Run once per profile that has one. Drafts keep their directory leaf names and installed characters keep their slugs, so a stored draft id still resolves; a draft carrying no `hermes_home` is stamped with the SOURCE home BEFORE it moves, because afterwards the directory no longer witnesses where it lived. A destination that already holds the leaf or slug is a per-entry REFUSAL, never a merge and never an overwrite, and nothing is deleted — the emptied source tree is left standing as its own tombstone. Idempotent: a second run moves nothing")
    characters_migrate_home.add_argument("--json", action="store_true")
    characters_migrate_home.set_defaults(func=_cmd_characters_migrate_home)
    characters_status = characters_subs.add_parser("status", help="Full draft state: stage, spec, per-item QA history")
    characters_status.add_argument("--draft", required=True, help="Draft id from `harness characters list`")
    characters_status.add_argument("--json", action="store_true")
    characters_status.set_defaults(func=_cmd_characters_status)
    characters_thumb = characters_subs.add_parser("thumb", help="Write a card-size QA crop of ONE FRAME of one row attempt (chroma keyed out, NEAREST upscale on a flat dark backdrop) and return its path")
    characters_thumb.add_argument("--draft", required=True)
    # One crop verb, two QA item kinds — the same two budget booleans for both.
    # A direction reference used to have no crop verb at all, which left the
    # launcher's card drawing a tile through the whole turnaround stage for want
    # of an ANSWER, never for want of a safe picture.
    characters_thumb_item = characters_thumb.add_mutually_exclusive_group(required=True)
    characters_thumb_item.add_argument("--row", help="An authored row key, e.g. walk-n")
    characters_thumb_item.add_argument("--direction", default="", help="An authored direction, e.g. e — crops that direction's turnaround REFERENCE instead of a row strip. Mirrored directions are never drawn and are refused. A reference holds one pose, so --frame does not apply to it")
    characters_thumb.add_argument("--attempt", type=int, default=-1, help="Which attempt to crop, 0-based as in `status --json` history; -1 = latest")
    # No defaults spelled here: the numbers live in `draft.DEFAULT_THUMB_SCALE` /
    # `draft.DEFAULT_THUMB_FRAME` and are resolved in the handler, which is also
    # where charsheet is imported — build_parser runs for EVERY harness call and
    # must not pull in Pillow.
    characters_thumb.add_argument("--frame", type=int, default=None, help="Which frame cell of the strip to crop, 0-based (default 0); the crop is the half that removes pixels, so there is always one")
    characters_thumb.add_argument("--scale", type=int, default=None, help="NEAREST upscale factor (default 2); refused, never clamped. At or below the default the OUTPUT must fit the console's fixed decode ceiling; above it the crop is a fullscreen-viewer artifact, bounded by the write ceiling and reported as withinConsoleBudget=false. The payload carries a SECOND bound, withinOwnSheet — is the crop no larger than the sheet THIS draft composes — which refuses nothing and is reported at every scale. Draw a crop inline only when BOTH are true; otherwise open it in the viewer")
    characters_thumb.add_argument("--square", action="store_true", help="Pad the finished crop onto a square flat-dark backdrop (side = the longer edge, cell centred) so the console's 1:1 centre-cover hero card shows the WHOLE frame instead of a torso zoom. The filename gains -sq and the payload says square: true. Both budget booleans are weighed on the padded output. Use it for a hero card; take the bare crop for a compare pair, whose panes align on today's shapes")
    characters_thumb.add_argument("--json", action="store_true")
    characters_thumb.set_defaults(func=_cmd_characters_thumb)
    characters_base = characters_subs.add_parser("base", help="Set or replace the draft's base identity image")
    characters_base.add_argument("--draft", required=True)
    characters_base.add_argument("--image", required=True, help="Path to the identity-anchor image; copied into the draft")
    characters_base.add_argument("--json", action="store_true")
    characters_base.set_defaults(func=_cmd_characters_base)
    characters_turnaround = characters_subs.add_parser("turnaround", help="Generate the authored direction references (stage 'turnaround')")
    characters_turnaround.add_argument("--draft", required=True)
    characters_turnaround.add_argument("--json", action="store_true")
    characters_turnaround.set_defaults(func=_cmd_characters_turnaround)
    characters_reroll_direction = characters_subs.add_parser("reroll-direction", help="Re-generate ONE direction reference, with an optional operator note")
    characters_reroll_direction.add_argument("--draft", required=True)
    characters_reroll_direction.add_argument("--direction", required=True, help="An authored direction, e.g. ne (mirrored directions are never generated)")
    characters_reroll_direction.add_argument("--note", default="", help="Operator note appended to the prompt and stored with the attempt")
    characters_reroll_direction.add_argument("--json", action="store_true")
    characters_reroll_direction.set_defaults(func=_cmd_characters_reroll_direction)
    characters_approve_direction = characters_subs.add_parser("approve-direction", help="Approve direction references; advances to stage 'rows' once all are approved")
    characters_approve_direction.add_argument("--draft", required=True)
    characters_approve_direction_which = characters_approve_direction.add_mutually_exclusive_group(required=True)
    characters_approve_direction_which.add_argument("--direction", default="", help="Approve this one direction")
    characters_approve_direction_which.add_argument("--all", dest="approve_all", action="store_true", help="Approve the latest attempt of every authored direction")
    characters_approve_direction.add_argument("--attempt", type=int, default=-1, help="Which attempt to approve; -1 = latest (single-direction only)")
    characters_approve_direction.add_argument("--json", action="store_true")
    characters_approve_direction.set_defaults(func=_cmd_characters_approve_direction)
    characters_rows = characters_subs.add_parser("rows", help="Generate the animation row strips (stage 'rows')")
    characters_rows.add_argument("--draft", required=True)
    characters_rows.add_argument("--only", default="", help="Restrict the run to these row keys, e.g. 'walk-e,walk-ne'")
    characters_rows.add_argument("--json", action="store_true")
    characters_rows.set_defaults(func=_cmd_characters_rows)
    characters_reroll_row = characters_subs.add_parser("reroll-row", help="Re-generate ONE row strip, with an optional operator note")
    characters_reroll_row.add_argument("--draft", required=True)
    characters_reroll_row.add_argument("--row", required=True, help="An authored row key, e.g. walk-e")
    characters_reroll_row.add_argument("--note", default="", help="Operator note appended to the prompt and stored with the attempt")
    characters_reroll_row.add_argument("--json", action="store_true")
    characters_reroll_row.set_defaults(func=_cmd_characters_reroll_row)
    characters_compose = characters_subs.add_parser("compose", help="Compose, validate and install the sheet (stage 'rows' → 'composed')")
    characters_compose.add_argument("--draft", required=True)
    characters_compose.add_argument("--accept-handedness", default="", help="Mirrored-art REFUSALS you have looked at and are overriding, spelled '<row>:<basis>' — take the spelling from the refusal. Per row, never blanket. TWO shapes refuse and both can be accepted: a row BOTH passes agree about ('idle-e:rotation+states'), and a row carried by a whole mirrored STATE, where every judged row of that state reads as a mirror ('jumping-e:states') — that one is accepted row by row like any other. A single-basis finding about a single row is a warning and there is nothing to accept. The basis is named on purpose: a bare row key waived a second, independent body of evidence at once. Naming a row that was not flagged is itself refused, and the honoured list rides on the installed manifest, 'characters list' and the sprite payload as {row, gain, basis}")
    characters_compose.add_argument("--json", action="store_true")
    characters_compose.set_defaults(func=_cmd_characters_compose)
    characters_auto = characters_subs.add_parser("auto", help="Drive the whole pipeline in ONE process — turnaround, approve every direction, generate the missing rows, compose and install — printing a receipt line as each stage lands. For an operator's EXPLICIT 'drive it all the way' ask and nothing else: it auto-approves the turnaround, which is the last moment a reference can change. It never overrides a handedness refusal (there is no --accept-handedness here) and it writes the same per-attempt history the interactive verbs write, so `reopen` repair and every QA crop work exactly as they do after a hand-driven run. It resumes rather than restarts: a stage whose work already exists is skipped, with the reason on the summary line, so running it after `reopen` regenerates the missing rows instead of discarding the approved ones. Output is newline-delimited — with --json every line is ONE compact object, and the LAST line is always the summary")
    characters_auto.add_argument("--draft", required=True)
    characters_auto.add_argument("--through", default="compose", choices=list(_CHARACTERS_AUTO_STEPS), help="Last step to run (default: compose, the whole pipeline). Steps before it that the draft already carries are skipped and reported")
    characters_auto.add_argument("--json", action="store_true")
    characters_auto.set_defaults(func=_cmd_characters_auto)
    characters_reopen = characters_subs.add_parser("reopen", help="Reopen a composed draft for fixes (stage 'composed' → 'rows'); the installed sheet stays until the next compose")
    characters_reopen.add_argument("--draft", required=True)
    characters_reopen.add_argument("--json", action="store_true")
    characters_reopen.set_defaults(func=_cmd_characters_reopen)
    characters_add_state = characters_subs.add_parser("add-state", help="Add ONE animation state to a draft at stage 'rows' (reopen a composed draft first); the new rows start un-generated and no approved row is touched")
    characters_add_state.add_argument("--draft", required=True)
    characters_add_state.add_argument("--state", required=True, help="One state in the --states grammar: 'jumping:6' or 'cheer:4:fixed'. Frames 2..8 — a one-frame row is refused HERE rather than several generations later at 'rows'")
    characters_add_state.add_argument("--json", action="store_true")
    characters_add_state.set_defaults(func=_cmd_characters_add_state)
    characters_sprite = characters_subs.add_parser("sprite", help="Return an installed character spritesheet payload")
    characters_sprite.add_argument("slug")
    characters_sprite.add_argument("--no-sheet", dest="no_sheet", action="store_true", help="Metadata only: drop `spritesheetBase64` (468.8 KiB of it on the live 3-state character, and the sheet bytes are not read at all) and carry `sheet`, the absolute path, in its place. `spritesheetRevision` and every geometry/taxonomy key are unchanged, so a consumer that wants framesByRow/states/rows and reads the file itself pays kilobytes instead of half a megabyte. The default is byte-identical to what it always was")
    characters_sprite.add_argument("--json", action="store_true")
    characters_sprite.set_defaults(func=_cmd_characters_sprite)
    characters_payload_contract = characters_subs.add_parser("payload-contract", help="Publish the KEY SET every `characters` READ payload can carry — the cross-repo contract the launcher commits and diffs, so the two sides disagree in a file instead of at runtime. Derived by RUNNING the verbs against a throwaway library in a temp directory (the real library is never touched), never from a hand-written list, so a key a producer grows or drops is in the dump the day it moves. Key PATHS only and never a value, so the dump is byte-stable. Conditional keys are marked with the modes that carry them — `spritesheetBase64` and `sheet` are one slot spelled two ways, which a flat key list cannot express")
    characters_payload_contract.add_argument("--json", action="store_true")
    characters_payload_contract.set_defaults(func=_cmd_characters_payload_contract)
