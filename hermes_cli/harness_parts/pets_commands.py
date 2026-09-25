"""``hermes harness pets``: gallery, install, sprite and thumb for installed pets.

Separate from the ``characters`` package because a pet is an installed artifact;
a character is a draft moving through the charsheet pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.cli_format import emit_json

__layer__ = "lanes"
__all__ = [
    "_cmd_pets_gallery",
    "_cmd_pets_install",
    "_cmd_pets_sprite",
    "_cmd_pets_thumb",
    "_installed_pet_gallery_row",
    "_pet_row_frame_counts",
    "_pet_sheet_revision",
    "_pet_sprite_payload_for_launcher",
    "_pet_state_rows",
]


def _cmd_pets_gallery(args) -> int:
    from agent.pet import store

    query = str(getattr(args, "query", "") or "").strip().lower()
    limit = max(0, int(getattr(args, "limit", 0) or 0))
    local_only = bool(getattr(args, "local_only", False))
    installed = {pet.slug: pet for pet in store.installed_pets()}
    rows: list[dict] = []
    seen: set[str] = set()
    manifest_error = ""

    if not local_only:
        try:
            from agent.pet.manifest import fetch_manifest

            entries = fetch_manifest()
            if query:
                entries = [
                    entry
                    for entry in entries
                    if query in entry.slug.lower() or query in entry.display_name.lower()
                ]
            if limit:
                entries = entries[:limit]
            for entry in entries:
                seen.add(entry.slug)
                rows.append(
                    {
                        "slug": entry.slug,
                        "displayName": entry.display_name,
                        "kind": entry.kind,
                        "submittedBy": entry.submitted_by,
                        "installed": entry.slug in installed,
                        "spritesheetUrl": entry.spritesheet_url,
                        "petJsonUrl": entry.pet_json_url,
                        "zipUrl": entry.zip_url,
                        "curated": "/curated/" in entry.spritesheet_url,
                        "generated": entry.slug in installed and installed[entry.slug].generated,
                    }
                )
        except Exception as exc:  # noqa: BLE001 - Launcher can still use local pets
            manifest_error = f"manifest unavailable: {exc}"

    for slug, pet in installed.items():
        if slug in seen:
            continue
        if query and query not in slug.lower() and query not in pet.display_name.lower():
            continue
        rows.append(_installed_pet_gallery_row(pet))

    data = {"ok": True, "localOnly": local_only, "pets": rows}
    if manifest_error:
        data["manifestError"] = manifest_error
    print(emit_json(data) if getattr(args, "json", False) else json.dumps(data, indent=2))
    return 0


def _cmd_pets_install(args) -> int:
    from agent.pet import store
    from agent.pet.manifest import ManifestError

    slug = str(getattr(args, "slug", "") or "").strip()
    try:
        pet = store.install_pet(slug, force=bool(getattr(args, "force", False)))
    except (store.PetStoreError, ManifestError) as exc:
        data = {"ok": False, "slug": slug, "error": str(exc)}
        print(emit_json(data) if getattr(args, "json", False) else data["error"])
        return 2
    data = {"ok": True, "pet": _installed_pet_gallery_row(pet)}
    print(emit_json(data) if getattr(args, "json", False) else json.dumps(data, indent=2))
    return 0


def _cmd_pets_sprite(args) -> int:
    from agent.pet import store

    slug = str(getattr(args, "slug", "") or "").strip()
    pet = store.load_pet(slug)
    if pet is None or not pet.exists:
        data = {"ok": False, "slug": slug, "error": f"pet '{slug}' is not installed"}
        print(emit_json(data) if getattr(args, "json", False) else data["error"])
        return 2
    data = {
        "ok": True,
        "pet": _pet_sprite_payload_for_launcher(
            pet, include_sheet=not bool(getattr(args, "no_sheet", False))
        ),
    }
    print(emit_json(data) if getattr(args, "json", False) else json.dumps(data, indent=2))
    return 0


def _cmd_pets_thumb(args) -> int:
    import base64

    from agent.pet import store

    slug = str(getattr(args, "slug", "") or "").strip()
    data = store.thumbnail_png(slug, source_url=str(getattr(args, "url", "") or ""))
    payload = (
        {"ok": True, "slug": slug, "dataUri": "data:image/png;base64," + base64.standard_b64encode(data).decode("ascii")}
        if data
        else {"ok": False, "slug": slug}
    )
    print(emit_json(payload) if getattr(args, "json", False) else json.dumps(payload, indent=2))
    return 0


def _installed_pet_gallery_row(pet) -> dict:
    return {
        "slug": pet.slug,
        "displayName": pet.display_name,
        "description": pet.description,
        "kind": "local",
        "submittedBy": "",
        "installed": True,
        "spritesheetUrl": "",
        "petJsonUrl": "",
        "zipUrl": "",
        "curated": False,
        "generated": pet.generated,
        # The producer the launcher's revision-keyed sprite-cache eviction has
        # been waiting for. That eviction (``PetdexSpriteCache
        # .noteSpritesheetRevision``) was built and gated on 2026-08-21 with no
        # writer on this side: hermes stamped ``spritesheetRevision`` only on the
        # ``pets sprite`` payload, which the launcher reads AFTER it has already
        # decided whether its resident decode is stale. A cache key nothing
        # produces is a cache key that never fires, so the only live
        # invalidation writers were the explicit clear paths.
        #
        # Same ``_pet_sheet_revision`` the sprite payload uses, deliberately: two
        # producers of one key would drift, and the launcher compares the value
        # from THIS row against the one the sprite payload stamped into its
        # resident decode. Different arithmetic here would evict every sheet on
        # every gallery read.
        #
        # REMOTE manifest rows above stay unstamped, and that is the honest
        # answer rather than an omission: their sheet is the one behind
        # ``spritesheetUrl``, which this process cannot stat. A revision
        # fabricated from something else would be a key that means nothing, and
        # the launcher — which correctly treats an unstamped sheet as "no
        # evidence of staleness" rather than as stale — would start evicting on
        # it. A sheet that cannot be stat'd at all lands here as the empty
        # string, which that same reader already handles as unstamped.
        "spritesheetRevision": _pet_sheet_revision(pet.spritesheet),
    }


def _pet_sheet_revision(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError:
        return ""
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _pet_row_frame_counts(spritesheet: Path) -> dict[str, int]:
    try:
        from PIL import Image

        from agent.pet import constants, render

        with Image.open(spritesheet) as opened:
            image = opened.convert("RGBA")
        cols = max(1, image.width // constants.FRAME_W)
        row_count = max(1, image.height // constants.FRAME_H)
        rows = constants.state_rows_for_grid(row_count)
        out: dict[str, int] = {}
        for row_idx, name in enumerate(rows[:row_count]):
            top = row_idx * constants.FRAME_H
            count = 0
            for col in range(cols):
                left = col * constants.FRAME_W
                frame = image.crop((left, top, left + constants.FRAME_W, top + constants.FRAME_H))
                if render._frame_is_blank(frame):
                    break
                count += 1
            out[name] = count
        return out
    except Exception:  # noqa: BLE001 - cosmetic payload; renderer can fall back
        return {}


def _pet_state_rows(spritesheet: Path) -> list[str]:
    try:
        from PIL import Image

        from agent.pet import constants

        with Image.open(spritesheet) as opened:
            row_count = max(1, opened.height // constants.FRAME_H)
        return list(constants.state_rows_for_grid(row_count))
    except Exception:  # noqa: BLE001
        from agent.pet import constants

        return list(constants.STATE_ROWS)


def _pet_sprite_payload_for_launcher(pet, *, include_sheet: bool = True) -> dict:
    """The launcher payload for an installed pet.

    ``include_sheet=False`` is the METADATA-ONLY shape (``pets sprite
    --no-sheet``, row 33), mirroring ``characters sprite --no-sheet``: it
    drops ``spritesheetBase64`` and puts ``sheet`` — the absolute path — in
    the same slot, so a consumer that wants ``framesByRow``/``stateRows`` and
    reads the file itself is not also handed the whole sheet re-encoded as
    base64. Unlike the character-sheet mode, the geometry keys below
    (``framesByRow``, ``framesByState``, ``stateRows``) still open the pet's
    sheet — a pet carries no per-row frame count in its manifest, so the
    padding-trimmed counts can only come from the image itself; only the
    WHOLE-SHEET base64 encode is skipped. The default is byte-identical to
    what it always was.
    """

    import base64

    from agent.pet import constants, render

    suffix = pet.spritesheet.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/webp"
    sheet_slot = (
        {"spritesheetBase64": base64.standard_b64encode(pet.spritesheet.read_bytes()).decode("ascii")}
        if include_sheet
        else {"sheet": str(pet.spritesheet)}
    )
    return {
        "slug": pet.slug,
        "displayName": pet.display_name,
        "description": pet.description,
        "mime": mime,
        **sheet_slot,
        "spritesheetRevision": _pet_sheet_revision(pet.spritesheet),
        "frameW": constants.FRAME_W,
        "frameH": constants.FRAME_H,
        "framesPerState": constants.FRAMES_PER_STATE,
        "framesByState": render.state_frame_counts(pet.spritesheet),
        "framesByRow": _pet_row_frame_counts(pet.spritesheet),
        "loopMs": constants.LOOP_MS,
        "scale": constants.DEFAULT_SCALE,
        "stateRows": _pet_state_rows(pet.spritesheet),
    }
