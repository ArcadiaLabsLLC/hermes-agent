"""``characters`` verbs outside the pipeline steps.

Start, list, status, thumb, sprite, base, reopen, add-state, the home
backfill/migrate pair, and payload-contract.
"""

from __future__ import annotations

from pathlib import Path

from .payloads import (
    _CHARACTERS_EXPECTED,
    _attempt_label,
    _characters_draft_summary,
    _characters_emit,
    _characters_error,
    _characters_installed_rows,
    _characters_next,
    _characters_verb,
)

__layer__ = "lanes"
__all__ = [
    "_cmd_characters_add_state",
    "_cmd_characters_backfill_home",
    "_cmd_characters_base",
    "_cmd_characters_list",
    "_cmd_characters_migrate_home",
    "_cmd_characters_payload_contract",
    "_cmd_characters_reopen",
    "_cmd_characters_sprite",
    "_cmd_characters_start",
    "_cmd_characters_status",
    "_cmd_characters_thumb",
]


def _cmd_characters_start(args) -> int:
    from agent.charsheet import spec as charsheet_spec
    from agent.charsheet.draft import CharacterDraft

    states_text = str(getattr(args, "states", "") or "").strip()
    base_text = str(getattr(args, "base_image", "") or "").strip()
    try:
        # An empty --states means "the CHAR8 states" — taken from CHAR8 itself
        # rather than re-spelled as a default string, so the default has one home.
        states = charsheet_spec.parse_states(states_text) if states_text else charsheet_spec.CHAR8.states
        scheme = charsheet_spec.parse_directions(str(getattr(args, "directions", "8") or "8"))
        sheet_spec = charsheet_spec.SheetSpec(states=states, scheme=scheme)
        draft = CharacterDraft.create(
            concept=str(getattr(args, "concept", "") or ""),
            slug=str(getattr(args, "slug", "") or ""),
            display_name=str(getattr(args, "display_name", "") or ""),
            style=str(getattr(args, "style", "auto") or "auto"),
            spec=sheet_spec,
            # Passed to create() rather than set after it, so a draft is never
            # observable without the anchor the operator asked it to have.
            base_image=Path(base_text).expanduser() if base_text else None,
            authored_by=str(getattr(args, "authored_by", "") or ""),
        )
    except _CHARACTERS_EXPECTED as exc:
        return _characters_error(args, exc)
    data = {"ok": True, "draft": draft.id, "stage": draft.stage, "summary": _characters_draft_summary(draft)}
    # The pipeline's first hint, and it reads the draft rather than the plan: a
    # draft started WITHOUT `--base-image` is the CS-5 repair shape, and
    # `turnaround` refuses without the anchor. Naming it there would hand the
    # caller the one round-trip this key exists to remove, so the anchorless
    # draft is pointed at the verb that repairs it. `<image>` is the single thing
    # the runtime cannot know.
    data["next"] = (
        _characters_next("turnaround", "--draft", draft.id)
        if draft.base_image is not None
        else _characters_next("base", "--draft", draft.id, "--image", "<image>")
    )
    return _characters_emit(
        args,
        data,
        f"Draft {draft.id} ({draft.slug}) created at stage '{draft.stage}': "
        f"{len(draft.spec.rows())} rows, {len(draft.spec.scheme.order)} directions",
    )


def _cmd_characters_list(args) -> int:
    from agent.charsheet.draft import CharacterDraft

    try:
        drafts = [_characters_draft_summary(draft) for draft in CharacterDraft.list_drafts()]
        installed = _characters_installed_rows()
    except _CHARACTERS_EXPECTED as exc:
        return _characters_error(args, exc)
    data = {"ok": True, "drafts": drafts, "characters": installed}
    lines = [f"{len(drafts)} draft(s), {len(installed)} installed character(s)"]
    lines += [f"  draft {row['id']}  {row['slug']}  stage={row['stage']}" for row in drafts]
    lines += [
        f"  installed {row['slug']}  {row['displayName']}"
        + (
            "  handedness accepted: "
            + ", ".join(
                f"{entry['row']} {entry['gain'] * 100:.0f}% ({entry['basis']})"
                for entry in row["handednessAccepted"]
            )
            if row["handednessAccepted"]
            else ""
        )
        for row in installed
    ]
    return _characters_emit(args, data, "\n".join(lines))


def _cmd_characters_backfill_home(args) -> int:
    """Stamp `hermes_home` on the library drafts that lack it, with THIS run's home.

    **Why a verb, and not a hook.** Doing it on LOAD turns every read into a
    disk writer — `characters list` is the launcher's cached polling read, and a
    read-that-writes races any concurrent mutation of the same draft for the
    rest of time. Doing it on the next MUTATION never reaches the dormant drafts
    that are the entire backfill population, and hides a provenance write inside
    every unrelated receipt. An explicit verb is bounded to the moment an
    operator chose, and its receipt is the evidence that it was.

    **The receipt names directories beside ids.** Two drafts can carry the same
    `id` — a copied draft keeps the id inside its `draft.json` — so an id-only
    receipt cannot say which of the two directories was written, which is the
    one thing an operator reading it afterwards needs to know.
    """
    from agent.charsheet.draft import CharacterDraft
    from hermes_constants import get_hermes_home

    home = str(get_hermes_home())
    try:
        stamped: list[dict] = []
        skipped: list[dict] = []
        # `list_drafts` already skips the unreadable ones, with a warning — a
        # draft this cannot parse is not a draft this may rewrite.
        for draft in CharacterDraft.list_drafts():
            row = {"id": draft.id, "directory": str(draft.directory)}
            if draft.record_home():
                stamped.append(row)
            else:
                skipped.append({**row, "hermesHome": draft.hermes_home})
    except _CHARACTERS_EXPECTED as exc:
        return _characters_error(args, exc)
    data = {"ok": True, "home": home, "stamped": stamped, "skipped": skipped}
    lines = [f"{len(stamped)} draft(s) stamped with {home}; {len(skipped)} already recorded"]
    lines += [f"  stamped {row['id']}  {row['directory']}" for row in stamped]
    # The DIRECTORY rides on this arm too. The skipped rows are exactly the
    # population an id cannot disambiguate — a copied draft keeps the id inside
    # its `draft.json` AND keeps the home it was made in, so the two rows an
    # id-collision produces here differ in nothing BUT their directory.
    lines += [
        f"  skipped {row['id']}  {row['directory']}  already {row['hermesHome']}"
        for row in skipped
    ]
    return _characters_emit(args, data, "\n".join(lines))


def _cmd_characters_migrate_home(args) -> int:
    """Move this home's legacy character store into the install-wide library.

    **The source is spelled literally, and that is not laziness.** It is
    `get_hermes_home() / "characters"` written out here rather than resolved
    through `characters_dir()`, because after the head-home that function answers
    the DESTINATION — a source resolved through it would ask the verb to move
    the library onto itself. This is the one site in hermes that is allowed to
    name the legacy location, and it names it because the location is legacy:
    nothing writes there any more, and this verb exists to empty it once.

    **Explicit and per-home, not a sweep.** One invocation migrates ONE home, the
    `backfill-home` operational pattern: the receipt stays attributable to the
    home the operator named, and the verb never has to enumerate profiles —
    which is the per-home resolution the launcher refused to do and hermes has
    no better claim to guess at. The operator runs it once per profile that has
    a store.
    """
    from agent.charsheet.draft import migrate_characters_home
    from hermes_constants import get_hermes_home
    from agent_runtime.profile_home import get_shared_characters_dir

    home = get_hermes_home()
    try:
        receipt = migrate_characters_home(
            home / "characters", get_shared_characters_dir(), source_home=str(home)
        )
    except _CHARACTERS_EXPECTED as exc:
        return _characters_error(args, exc)
    moved, stamped, skipped = receipt["moved"], receipt["stamped"], receipt["skipped"]
    lines = [
        f"{len(moved)} entr(ies) moved from {receipt['from']} to {receipt['to']}; "
        f"{len(stamped)} stamped, {len(skipped)} skipped"
    ]
    # Every line names the DIRECTORY beside the id or slug, for the reason the
    # backfill's receipt does: an id-collision pair lists twice under one id, and
    # the directory is the only thing that says which entry a row is about.
    lines += [
        f"  moved {row['kind']} {row.get('id') or row.get('slug')}  {row['from']} -> {row['to']}"
        for row in moved
    ]
    lines += [f"  stamped {row['id']}  {row['directory']}" for row in stamped]
    # The skipped arm was the exception the comment above did not know it had:
    # a refusal is the row an operator has to ACT on — the entry is still
    # sitting somewhere and they have to go look at it — so it is the last one
    # that may print an id the collision pair makes ambiguous.
    lines += [
        f"  skipped {row['kind']} {row.get('id') or row.get('slug')}  "
        f"{row['directory']}  {row['reason']}"
        for row in skipped
    ]
    return _characters_emit(args, receipt, "\n".join(lines))


def _cmd_characters_status(args) -> int:
    def call(draft):
        status = draft.status_payload()
        return {"status": status}, (
            f"Draft {draft.id} ({draft.slug}) at stage '{draft.stage}'; pending "
            f"turnaround={status['pending']['turnaround']} rows={status['pending']['rows']}"
        )

    return _characters_verb(args, call)


def _cmd_characters_thumb(args) -> int:
    # A path, never bytes: the crop is written into the draft and the payload
    # names it (plan A-4). `pets thumb` answers with a data URI because a Petdex
    # gallery row may come from a remote sheet; a draft's attempts are always on
    # this disk, and the launcher reads them there.
    from agent.charsheet.draft import DEFAULT_THUMB_FRAME, DEFAULT_THUMB_SCALE

    row_key = str(getattr(args, "row", "") or "").strip()
    direction = str(getattr(args, "direction", "") or "").strip()
    attempt = int(getattr(args, "attempt", -1))
    requested_frame = getattr(args, "frame", None)
    frame = DEFAULT_THUMB_FRAME if requested_frame is None else int(requested_frame)
    requested_scale = getattr(args, "scale", None)
    scale = DEFAULT_THUMB_SCALE if requested_scale is None else int(requested_scale)
    square = bool(getattr(args, "square", False))

    def call(draft):
        if direction:
            # A reference holds ONE pose. Ignoring `--frame` here would answer a
            # caller who asked for cell 3 with cell 0 and call it a crop.
            if requested_frame is not None:
                raise ValueError(
                    "--frame addresses a cell of a row STRIP; a direction "
                    f"reference is one pose, so `--direction {direction}` and "
                    "--frame cannot be asked for together"
                )
            result = draft.direction_thumb(
                direction, attempt=attempt, scale=scale, square=square
            )
        else:
            result = draft.row_thumb(
                row_key, attempt=attempt, frame=frame, scale=scale, square=square
            )
        # An agent reads the human line as often as the payload, and the one
        # thing it must not do with a deep zoom is declare it with `MEDIA:`. So
        # the line says which artifact this is, not just how big it came out.
        #
        # TWO bounds, and the line names WHICH one a crop missed, because the
        # remedy differs: over the console ceiling means the decode itself is
        # unsafe, while heavier-than-your-own-sheet means the crop is safe and
        # simply bought nothing. Inline only when both hold — the same rule
        # `row_thumb`'s docstring states for the launcher card.
        if not result["withinConsoleBudget"]:
            weight = " — over the console's decode ceiling; open it in the viewer, never as a card"
        elif not result["withinOwnSheet"]:
            weight = " — heavier than this draft's own sheet, so cropping bought nothing; open it in the viewer"
        else:
            weight = ""
        # And WHICH SHAPE, because the two are used for different things: a
        # padded square is the hero-card crop, a bare cell is what a compare
        # pair's panes align on.
        shape = ", padded square" if result["square"] else ""
        # WHICH item, in the item's own vocabulary: a row crop names its frame
        # because an operator judges a row frame by frame, and a reference has
        # no frame to name. Saying "frame 1 of 1" for a reference would invite
        # the reader to go looking for frame 2.
        subject = (
            f"direction {result['direction']} reference "
            if direction
            else f"row {result['row']} "
        )
        frames = "" if direction else f"frame {result['frame'] + 1} of {result['frames']}, "
        return result, (
            f"Draft {draft.id}: {subject}"
            f"{_attempt_label(result['attempt'], result['attempts'])}, "
            f"{frames}"
            f"cropped at {result['width']}x{result['height']} "
            f"({result['scale']}x{shape}) → {result['path']}{weight}"
        )

    return _characters_verb(args, call)


def _cmd_characters_base(args) -> int:
    # Repairs a draft started without --base-image (CS-5 finding: without this
    # verb such a draft could never advance) and covers the base-pick flow.
    def call(draft):
        target = draft.set_base_image(str(getattr(args, "image", "") or "").strip())
        return {"baseImage": str(target)}, f"Draft {draft.id}: base image set to {target}"

    return _characters_verb(args, call)


def _cmd_characters_reopen(args) -> int:
    def call(draft):
        result = draft.reopen()
        return result, (
            f"Draft {draft.id} reopened at stage {result['stage']} "
            "(installed sheet unchanged until the next compose)"
        )

    return _characters_verb(args, call)


def _cmd_characters_add_state(args) -> int:
    state_text = str(getattr(args, "state", "") or "").strip()

    def call(draft):
        result = draft.add_state(state_text)
        state = result["state"]
        # The `--only` list is spelled out for the operator because `--only` has
        # NO glob: `run_rows` matches keys exactly and raises on any key it does
        # not author, so `jumping-*` is one unknown row key, not a wildcard. The
        # verb that knows the new keys is the verb that should hand them over.
        return result, (
            f"Draft {draft.id}: state {state['name']} added "
            f"({state['frames']} frames, "
            f"{'directional' if state['directional'] else 'fixed'}); "
            f"{len(result['rows'])} new row(s) to generate — "
            f"`characters rows --draft {draft.id} --only {','.join(result['rows'])}`"
        )

    return _characters_verb(args, call)


def _cmd_characters_sprite(args) -> int:
    from agent.charsheet import draft as charsheet_draft

    slug = str(getattr(args, "slug", "") or "").strip()
    try:
        payload = charsheet_draft.sprite_payload(
            slug, include_sheet=not bool(getattr(args, "no_sheet", False))
        )
    except _CHARACTERS_EXPECTED as exc:
        return _characters_error(args, exc, slug=slug)
    data = {"ok": True, "character": payload}
    accepted = payload.get("handednessAccepted") or []
    return _characters_emit(
        args,
        data,
        f"{payload['slug']} ({payload['displayName']}): {len(payload['framesByRow'])} rows, "
        f"{payload['frameW']}x{payload['frameH']} cells, revision {payload['spritesheetRevision']}"
        # The human line says where the bytes ARE exactly when it is not
        # carrying them. Reading the key off the payload rather than off
        # `args.no_sheet` keeps the two from drifting: the mode is the payload's
        # fact, and the flag is only how this handler asked for it.
        + (f", sheet {payload['sheet']}" if "sheet" in payload else "")
        + (
            "; handedness accepted: "
            + ", ".join(
                f"{entry['row']} {entry['gain'] * 100:.0f}% ({entry['basis']})"
                for entry in accepted
            )
            if accepted
            else ""
        ),
    )


def _cmd_characters_payload_contract(args) -> int:
    """Publish the key set of every `characters` READ payload.

    The artifact the launcher's fixture is vendored from. Everything about how
    the key set is measured — probing rather than declaring, two vocabularies to
    tell data keys from schema keys, modes for the conditional slot — lives in
    `hermes_cli/charsheet_payload_contract.py`, which is also where a new
    payload kind is added.

    It emits through `_characters_emit` like every other `characters` verb, so
    `--json` prints the document and a bare call prints a human line. There is
    no draft and no slug: the probes are built and thrown away inside the call.
    """
    from hermes_cli.charsheet_payload_contract import build_payload_contract

    document = build_payload_contract()
    kinds = document["payloads"]
    return _characters_emit(
        args,
        document,
        "; ".join(
            f"{name}: {len(kind['keys'])} keys"
            + (
                f" ({sum(1 for k in kind['keys'].values() if k['conditional'])} conditional)"
                if any(k["conditional"] for k in kind["keys"].values())
                else ""
            )
            for name, kind in sorted(kinds.items())
        ),
    )
