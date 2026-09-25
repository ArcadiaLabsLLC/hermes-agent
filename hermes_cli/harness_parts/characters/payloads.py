"""The payload shapes every ``characters`` verb emits: errors, refusals, ``next`` hints, rows.

Separate so the interactive verbs, the autopilot and the payload-contract dump
build one shape from one place.
"""

from __future__ import annotations

import json

from agent_runtime.cli_format import emit_json
from agent.charsheet.errors import CharsheetRefusal, DraftBusy

__layer__ = "policy"
__all__ = [
    "_CHARACTERS_EXPECTED",
    "_attempt_label",
    "_characters_draft_summary",
    "_characters_draftsman",
    "_characters_emit",
    "_characters_error",
    "_characters_installed_rows",
    "_characters_next",
    "_characters_refusal_extra",
    "_characters_verb",
]


# ───────────────────────── character sheets (charsheet) ─────────────────────────
#
# The launcher's transport for pets is a one-shot `--json` subprocess, so the
# character QA panel's backend is the same thing: these verbs, and nothing else.
# Each handler loads a draft and calls exactly one CharacterDraft method — the
# stage machine refuses out-of-order calls, so there is no ordering logic here to
# get out of sync with the backend's.


def _characters_error(args, exc: BaseException, **extra) -> int:
    """The pets error shape, verbatim: flat `{"ok": false, "error": …}`, exit 2.

    Not `emit_harness_error`: that emits the Stage-42 envelope (`error` as a
    nested object with a code taxonomy), and a launcher panel that already parses
    the pets shape should not have to learn a second one for its sibling verbs.
    """
    data = {"ok": False, "error": str(exc)}
    data.update(extra)
    print(emit_json({**data, **_characters_draftsman()}) if getattr(args, "json", False) else data["error"])
    return 2


def _characters_draftsman() -> dict:
    """``{"draftsman": "fake"}`` while the seam is armed, and NOTHING when it is not.

    Additive and conditional, in that order. Additive: the character payloads
    are ruled supersets, so a key that appears is free. Conditional, and never
    ``"real"``: an old reader must see byte-identical output on the door it has
    always used, so "absent" keeps meaning "the provider door" and the key
    exists only to make the OTHER case impossible to miss — a sandbox that
    forgot to arm the seam reads as a paid run rather than a silent one, and a
    field run that armed it by accident says so on every row it writes.

    Read per emit, not once: the variable belongs to the process, and a serve
    may be spawned by a launcher that set it (RL-26).
    """
    from agent.charsheet.fake_draftsman import active_draftsman_name

    name = active_draftsman_name()
    return {"draftsman": name} if name else {}


def _characters_next(verb: str, *flags: str, alternatives=()) -> dict:
    """The machine next-step hint: `{verb, cmd}`, and sometimes a second way on.

    Measured cause (turn-efficiency plan, Stage 4b): one authoring turn spent
    seven `--help` elements and a `characters --help` working out which verb came
    next and how to spell it. Every one of those is a full API round-trip that
    re-sends the whole turn context — 60-120k prompt tokens each, late in a heavy
    turn. A payload that names its own successor answers the question before it
    is asked, and it answers it for a caller with no skill in context at all.

    A COMMAND, not a verb name: a bare name still costs a `--help` to turn into a
    command line, which is the round-trip being removed. It is spelled with the
    `hermes` entrypoint the skill teaches rather than `python -m hermes_cli.main`
    — both resolve, but the long one is noise in every trace row and the operator
    trace truncates commands at 500 chars.

    `alternatives` carries the second legal move when there genuinely are two
    (a failed batch: re-roll the row that died, or resume the ones that never
    landed). One shape, so a consumer reads `next["cmd"]` and, if it wants the
    fork, `next["alternatives"]` — never a different key per verb.

    ADDITIVE and OPTIONAL. The payloads are ruled supersets, so a new key breaks
    no consumer; a verb with no next step omits `next` rather than carrying an
    empty one, because a hint naming a verb the draft would refuse costs the
    caller exactly the round-trip this exists to save.
    """
    hint = {
        "verb": verb,
        "cmd": " ".join(["hermes", "harness", "characters", verb, *flags, "--json"]),
    }
    if alternatives:
        hint["alternatives"] = list(alternatives)
    return hint


def _characters_emit(args, data: dict, human: str) -> int:
    print(emit_json({**data, **_characters_draftsman()}) if getattr(args, "json", False) else human)
    return 0


def _attempt_label(index: int, total: int | None = None) -> str:
    """How an attempt is SHOWN to a person: 1-based, and counted the same way.

    **A QA surface relabels, never renumbers.** Attempt indices are 0-based
    everywhere a machine reads them — the `status --json` history, `--attempt`,
    the revision store's one resolver — and the payloads emitted beside these
    lines keep that. But the store's own files are `attempt-1.png`,
    `attempt-2.png`, and a human line that said "attempt 0 of 3" put two
    different bases in one sentence and left an operator correlating a crop to
    a store file off by one. Every human line that shows an attempt renders it
    here, so the two numbering systems meet in exactly one place.
    """
    shown = f"attempt {index + 1}"
    return f"{shown} of {total}" if total is not None else shown


# What the backend raises for a refusal the operator can act on: a wrong stage, an
# unauthored direction, an unknown row key (ValueError); a missing draft or an
# uninstalled slug (FileNotFoundError); an --attempt out of range (IndexError);
# and the two TYPED refusals the charsheet package raises for conditions that are
# not about the request at all (`CharsheetRefusal` — a draft another generation
# already holds, a provider call past its deadline). Anything else is a bug and
# keeps its traceback.
#
# The typed pair deliberately does NOT ride `ValueError`. This tuple is the
# taxonomy the character lane actually reads — `emit_harness_error` /
# `_error_code_for_exception` are never called by any `characters` verb — so
# these two are caught HERE, and their `code` travels on the flat payload rather
# than being flattened into `invalid_request` by a mapping nothing on this lane
# consults.
_CHARACTERS_EXPECTED = (ValueError, FileNotFoundError, IndexError, CharsheetRefusal)


def _characters_refusal_extra(draft, exc: BaseException) -> dict:
    """What a TYPED charsheet refusal adds to the flat error payload.

    Two keys, both additive on a ruled superset (`_characters_next`):

    * ``code`` — the stable token (`draft_busy`, `provider_timeout`). A consumer
      that had to branch on the message text was branching on prose; the
      launcher's `CharaAuthoringOutcome.refused` already ignores keys it does
      not know, so this costs it nothing and gains it a test it can write.
    * ``busy`` — the HOLDER, for `draft_busy` only: verb, pid, host, start time,
      age, and the lock path. The last one is not decoration. There is no pid
      liveness on Windows (`os.kill(pid, 0)` kills the process — this repo's
      mutation gate refuses the probe for that reason), so a lock a crashed
      generation left behind is cleared by hand until the age ceiling laps it,
      and a refusal that withheld the path would leave the operator guessing.

    The ``next`` hint is `status` and nothing else. There genuinely is no second
    legal move — hermes cannot cancel a running generation
    (`serve.py`'s `cancel_denied`), so "wait, and look at what has landed" is
    the whole of it — and `_characters_next` is explicit that `alternatives`
    carries a second move only when there are two.
    """

    code = getattr(exc, "code", "")
    if not code:
        return {}
    extra: dict = {"code": code}
    if isinstance(exc, DraftBusy):
        details = getattr(exc, "safe_details", None)
        if details:
            extra["busy"] = dict(details)
        extra["next"] = _characters_next("status", "--draft", draft.id)
    return extra


def _characters_verb(args, call, on_error=None) -> int:
    """Load `--draft`, run one backend call, emit the house payload.

    *call* takes the draft and returns `(payload_dict, human_line)`. The draft id
    and the stage AFTER the call ride on every response: a verb can advance the
    stage, and the caller's next legal verb depends on knowing that it did.

    *on_error*, when given, takes `(draft, exception)` and returns extra keys for
    the REFUSAL payload — the one place a verb knows something about its own
    failure that the flat error shape cannot carry. It runs only for refusals a
    caller can act on (`_CHARACTERS_EXPECTED`); a bug still keeps its traceback.
    """
    from agent.charsheet.draft import CharacterDraft

    draft_id = str(getattr(args, "draft", "") or "").strip()
    try:
        draft = CharacterDraft.load(draft_id)
    except _CHARACTERS_EXPECTED as exc:
        return _characters_error(args, exc, draft=draft_id)
    try:
        result, human = call(draft)
    except _CHARACTERS_EXPECTED as exc:
        extra = dict((on_error(draft, exc) or {}) if on_error is not None else {})
        # LAST, so a typed refusal's own hint wins. `rows`'s `on_error` builds a
        # resume naming the rows that never landed — exactly right for a batch
        # that died mid-flight, and exactly wrong for a batch that was never
        # admitted because another writer holds the draft.
        extra.update(_characters_refusal_extra(draft, exc))
        return _characters_error(args, exc, draft=draft.id, stage=draft.stage, **extra)
    data = {"ok": True, "draft": draft.id, "stage": draft.stage}
    data.update(result)
    return _characters_emit(args, data, human)


def _characters_draft_summary(draft) -> dict:
    """A list row: identity and shape, without walking the revision store.

    ``baseImage`` answers with the SAME spelling of absence ``status --json``
    uses — a ``str`` or JSON ``null``, never ``""`` — through the one helper
    (``draft.path_or_none``). ``list`` and ``status`` name the same field, and a
    consumer that has to remember which of the two flattens absence is a
    consumer that will get it wrong.

    ``shadows`` is what makes a duplicate ``id`` readable rather than a defect.
    A backup directory is a copy of a draft directory, so it answers the
    ORIGINAL's id and two rows carried one id with nothing to tell them apart.
    The copy stays a row — it is on disk — and names the id it copies, so a
    consumer drops every row carrying ``shadows`` and keeps the un-shadowed one.
    ``str`` or JSON ``null``, the same spelling of absence as its neighbours.
    """
    from agent.charsheet.draft import path_or_none

    spec = draft.spec
    return {
        "id": draft.id,
        "slug": draft.slug,
        "displayName": draft.display_name,
        "concept": draft.concept,
        "style": draft.style,
        "shadows": draft.shadows,
        "authoredBy": draft.authored_by,
        # Beside `authoredBy` in all three payloads that carry provenance —
        # this row, `status --json`, and the `start --json` summary (which is
        # this helper) — so a consumer never has to remember which of the three
        # answers the question. `str` or JSON `null`, never `""`.
        "hermesHome": draft.hermes_home,
        "stage": draft.stage,
        "rows": len(spec.rows()),
        "authoredRows": len(spec.authored_rows()),
        "directions": len(spec.scheme.order),
        "baseImage": path_or_none(draft.base_image),
        "directory": str(draft.directory),
    }


def _characters_installed_rows() -> list[dict]:
    """Installed characters: one row per directory carrying a manifest.

    ``handednessAccepted`` rides on every row because the alternative is that a
    character carrying a mirrored row its operator overrode looks IDENTICAL here
    to one that passed clean — which is the shape this whole lane exists to
    retire. It is a list of ``{row, gain, basis}``, empty for nearly every
    character.

    ``palette`` is the compose-time colour table (``#RRGGBBAA``, most-used
    first) and is CONDITIONAL, unlike its neighbours: a character composed
    before the table existed carries no key at all rather than an empty list.
    "Nobody recorded a palette" and "this sheet has no colours" are different
    facts, and the launcher's swatch strip owes an old character a blank strip
    and a colourless one a defect report. See
    ``agent/charsheet/draft.py::read_palette``.
    """
    from agent.charsheet.draft import (
        MANIFEST_FILENAME,
        SHEET_FILENAME,
        _handedness_accepted,
        characters_dir,
        read_palette,
    )

    root = characters_dir()
    rows: list[dict] = []
    for child in sorted(root.iterdir()) if root.is_dir() else []:
        manifest_path = child / MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}
        sheet = child / SHEET_FILENAME
        palette = read_palette(child)
        rows.append(
            {
                "slug": str(manifest.get("slug", "") or child.name),
                "displayName": str(manifest.get("displayName", "") or child.name),
                "draftId": str(manifest.get("draftId", "")),
                "created": str(manifest.get("created", "")),
                "directory": str(child),
                "sheet": str(sheet) if sheet.is_file() else "",
                "installed": sheet.is_file(),
                **({"palette": palette} if palette is not None else {}),
                "handednessAccepted": _handedness_accepted(manifest),
            }
        )
    return rows
