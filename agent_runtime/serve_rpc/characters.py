"""``runtime.characters.list/status/thumb/sprite`` — the character-sheet read twins.

Argv census rows 16-19 (launcher ``argv-census-full-2026-10-03.md``): the four
``harness characters`` read verbs rode ``dispatch_argv``, so their payloads were
untyped and a remote aim could not read them — ``thumb`` and ``sprite --no-sheet``
answer a PATH, which is useless off-box. Each twin builds the argv verb's
``--json`` payload from the same builders (``agent.charsheet.draft.payloads``,
``status_payload``, ``sprite_payload``) and adds the pixels a remote reader needs
in the ``runtime.media.get`` block shape (:func:`serve_rpc.media.media_block`).

* ``thumb`` adds ``media``: the crop's block when ``withinConsoleBudget``, else
  ``null`` beside the existing ``path`` and the two bound booleans that say which
  bound was missed.
* ``sprite`` returns the METADATA-ONLY ``character`` (the ``--no-sheet`` shape)
  and, when ``include_sheet`` is true, ``sheet_media`` as a block in place of the
  bare ``spritesheetBase64`` string — ``null`` past the media lane's fetch cap.

**Refusals** use the argv refusal vocabulary: a typed ``CharsheetRefusal``
answers its own ``code`` as ``data.reason`` (``ERR_HANDLER_FAILED``); a missing
draft or uninstalled slug is ``not_found`` (``ERR_NOT_FOUND``); a wrong request
(an unknown row, an out-of-range attempt, ``frame`` with ``direction``) is
``invalid_request`` (``ERR_INVALID_PARAMS``). The argv message rides ``message``.

**Tiers.** All four are ``read``: views of the install's character library, no
write beyond the crop cache a thumb renders into.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_READ
from agent_runtime.param_readers import read_flag, read_text
from agent_runtime.serve_rpc.protocol import (
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    err,
    ok,
)
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "_runtime_characters_list",
    "_runtime_characters_sprite",
    "_runtime_characters_status",
    "_runtime_characters_thumb",
]

class _Invalid(ValueError):
    """A parameter of the wrong type; refused before any draft is loaded."""


def _charsheet_refusal(rid: Any, exc: BaseException, **extra: Any) -> dict:
    from agent.charsheet.errors import CharsheetRefusal

    if isinstance(exc, CharsheetRefusal):
        code, reason = ERR_HANDLER_FAILED, str(getattr(exc, "code", "") or "charsheet_refused")
    elif isinstance(exc, FileNotFoundError):
        code, reason = ERR_NOT_FOUND, "not_found"
    else:
        code, reason = ERR_INVALID_PARAMS, "invalid_request"
    return err(rid, code, str(exc) or reason, {"reason": reason, **extra})


def _expected() -> tuple[type[BaseException], ...]:
    from agent.charsheet.errors import CharsheetRefusal

    return (ValueError, FileNotFoundError, IndexError, CharsheetRefusal)


def _payload(data: dict) -> dict:
    from agent.charsheet.draft.payloads import draftsman

    return {**data, **draftsman()}


def _invalid_param(key: str, sentence: str) -> _Invalid:
    """The :data:`agent_runtime.param_readers.Refuse` this lane hands the shared readers."""

    return _Invalid(sentence)


def _int_or_default(params: dict, key: str, default: int | None) -> int | None:
    value = params.get(key, default)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise _Invalid(f"{key} must be an integer")
    return value


def _params(params: Any) -> dict:
    return params if isinstance(params, dict) else {}


def _draft_verb(rid: Any, draft_id: str, call) -> dict:
    """Load the draft, run one read, answer the argv ``_characters_verb`` payload."""
    from agent.charsheet.draft import CharacterDraft

    try:
        draft = CharacterDraft.load(draft_id)
    except _expected() as exc:
        return _charsheet_refusal(rid, exc, draft=draft_id)
    try:
        result = call(draft)
    except _expected() as exc:
        return _charsheet_refusal(rid, exc, draft=draft.id, stage=draft.stage)
    return ok(rid, _payload({"ok": True, "draft": draft.id, "stage": draft.stage, **result}))


@method("runtime.characters.list", tier=TIER_READ)
def _runtime_characters_list(rid: Any, params: dict, context=None) -> dict:
    """``harness characters list --json``: ``{ok, drafts: [row], characters: [row]}``."""
    from agent.charsheet.draft import CharacterDraft
    from agent.charsheet.draft.payloads import draft_summary, installed_rows

    try:
        drafts = [draft_summary(draft) for draft in CharacterDraft.list_drafts()]
        installed = installed_rows()
    except _expected() as exc:
        return _charsheet_refusal(rid, exc)
    return ok(rid, _payload({"ok": True, "drafts": drafts, "characters": installed}))


@method("runtime.characters.status", tier=TIER_READ)
def _runtime_characters_status(rid: Any, params: dict, context=None) -> dict:
    """``harness characters status --draft <id> --json``. Params: ``draft`` (required)."""
    try:
        draft_id = read_text(_params(params), "draft", refuse=_invalid_param, required=True)
    except _Invalid as exc:
        return _charsheet_refusal(rid, exc)
    return _draft_verb(rid, draft_id, lambda draft: {"status": draft.status_payload()})


@method("runtime.characters.thumb", tier=TIER_READ)
def _runtime_characters_thumb(rid: Any, params: dict, context=None) -> dict:
    """``harness characters thumb --json`` plus ``media``.

    Params: ``draft`` (required); ``row`` or ``direction``; ``attempt`` (int,
    default -1: the latest); ``frame``, ``scale`` (int); ``square`` (bool).
    """
    from agent.charsheet.draft.payloads import thumb_result

    params = _params(params)
    try:
        draft_id = read_text(params, "draft", refuse=_invalid_param, required=True)
        options = {"row_key": read_text(params, "row", refuse=_invalid_param) or "",
                   "direction": read_text(params, "direction", refuse=_invalid_param) or "",
                   "attempt": _int_or_default(params, "attempt", -1),
                   "requested_frame": _int_or_default(params, "frame", None),
                   "scale": _int_or_default(params, "scale", None),
                   "square": read_flag(params, "square", refuse=_invalid_param)}
    except _Invalid as exc:
        return _charsheet_refusal(rid, exc)

    def call(draft) -> dict:
        result = thumb_result(draft, **options)
        return {**result, "media": _thumb_media(result)}

    return _draft_verb(rid, draft_id, call)


def _thumb_media(result: dict) -> dict | None:
    """The crop's pixels, only inside the console's decode ceiling."""
    from pathlib import Path

    from agent_runtime.media_handles import handle_for_bytes
    from agent_runtime.serve_rpc.media import media_block

    if not result["withinConsoleBudget"]:
        return None
    data = Path(result["path"]).read_bytes()
    return media_block(handle_for_bytes(data), "image/png", data)


@method("runtime.characters.sprite", tier=TIER_READ)
def _runtime_characters_sprite(rid: Any, params: dict, context=None) -> dict:
    """``harness characters sprite --no-sheet --json`` plus ``sheet_media``.

    Params: ``slug`` (required); ``include_sheet`` (bool, default true).
    """
    from pathlib import Path

    from agent.charsheet import draft as charsheet_draft
    from agent_runtime.media_handles import MAX_FETCH_BYTES, handle_for_bytes
    from agent_runtime.serve_rpc.media import media_block

    params = _params(params)
    try:
        slug = read_text(params, "slug", refuse=_invalid_param, required=True)
        include_sheet = read_flag(params, "include_sheet", refuse=_invalid_param, default=True)
    except _Invalid as exc:
        return _charsheet_refusal(rid, exc)
    try:
        character = charsheet_draft.sprite_payload(slug, include_sheet=False)
        result: dict[str, Any] = {"ok": True, "character": character}
        if include_sheet:
            sheet = Path(character["sheet"])
            fits = sheet.stat().st_size <= MAX_FETCH_BYTES
            data = sheet.read_bytes() if fits else b""
            result["sheet_media"] = (
                media_block(handle_for_bytes(data), character["mime"], data) if fits else None)
    except _expected() as exc:
        return _charsheet_refusal(rid, exc, slug=slug)
    return ok(rid, _payload(result))
