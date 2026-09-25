# Workspace LEVEL CLI tier: `hermes harness level …`.
#
# This module shares the Stage-42 envelope/printer/error helpers
# with every other tier — imported from hermes_cli.harness_support below, not
# inherited. Both writes go through the LevelStore chokepoint, the same door
# realm sync's pull applier uses.
#
# THE CONTRACT, and the whole reason these two verbs exist: the launcher owns
# the level document's format and hermes owns its transport. `set` takes the
# launcher's `SceneSerializer` output and stores it VERBATIM; `show --full`
# hands the same bytes back. hermes validates exactly two facts about them (it
# is UTF-8 JSON, the object carries a `version`) and reformats nothing, because
# the day the backend's level routes land the transport is meant to be
# swappable without a format change.
#
# Design contract: EterniaLauncher
# docs/spatial/planned/one-engine-one-catalogue-levels-per-workspace.md (R15).

# A real module (lane H1, 2026-09-24): it imports everything it reads, and a
# test patches a name HERE, where this module looks it up — never on
# ``hermes_cli.harness`` (W0-G4, tests/tooling/test_harness_namespace_is_thin.py).

from __future__ import annotations

from pathlib import Path

from agent_runtime.root_observability import attach_root_observability
from agent_runtime.store import WorkspaceStore
from hermes_cli.harness_support import (
    load_document_bytes,
    _object_envelope,
    _print_stage42,
    emit_harness_error,
)

__layer__ = "lanes"
__all__ = [
    "_cmd_level_clear",
    "_cmd_level_set",
    "_cmd_level_show",
]



def _level_store():
    from agent_runtime.level_sync import LevelStore

    return LevelStore()


def _level_workspace_for(args) -> str | None:
    return getattr(args, "workspace", None) or WorkspaceStore().active_id()


def _level_row(workspace_id: str, token: str, raw: bytes | None, *, full: bool) -> dict:
    """One level row, built by the store module's own builder.

    ``token`` is accepted and asserted rather than used: every caller here
    already tokenized the workspace for its own messages, and the row's token
    has to be the one the RPC lane prints or the launcher's compare-and-set
    would key on two spellings. One builder, so it cannot.
    """

    from agent_runtime.level_sync import level_document_row

    row = level_document_row(workspace_id, raw, full=full)
    row["workspace_token"] = token or row["workspace_token"]
    return row


def _cmd_level_show(args) -> int:
    """`harness level show` — read one workspace's level back.

    ``--full`` carries the document itself, and the metadata-only default is the
    office family's (`office show --full`) rather than an opinion of its own: a
    1 MB JSON string on a table print is not an answer anyone reads, and the one
    caller that wants the bytes always knows it wants them.
    """

    store = _level_store()
    workspace = _level_workspace_for(args)
    if not workspace:
        return emit_harness_error(
            ValueError("no workspace selected; pass --workspace"), args=args, code="invalid_request"
        )
    from agent_runtime import paths

    token = paths.safe_path_token(workspace)
    row = _level_row(workspace, token, store.read(workspace), full=bool(getattr(args, "full", False)))
    _print_stage42(attach_root_observability(_object_envelope("level", row)), args=args)
    return 0


def _cmd_level_set(args) -> int:
    """`harness level set` — store one workspace's level VERBATIM.

    The refusal taxonomy is the store door's own (`LevelDocumentError.code`), not
    a second reading of the document here: `invalid_payload` for a document this
    runtime will not accept, with the typed word the store used carried through
    as ``reason`` so the launcher can say WHICH of the four it was rather than
    "the level was rejected".

    ``--dry-run`` validates and reports what WOULD change without writing, which
    is what makes "will hermes take this document" answerable before a publish
    carries it to every member of a realm.
    """

    from agent_runtime.level_sync import LevelDocumentError, validate_level_document

    store = _level_store()
    workspace = _level_workspace_for(args)
    if not workspace:
        return emit_harness_error(
            ValueError("no workspace selected; pass --workspace"), args=args, code="invalid_request"
        )
    try:
        raw = load_document_bytes(args.document)
    except OSError as exc:
        return emit_harness_error(exc, args=args, code="invalid_payload")
    try:
        validate_level_document(raw)
    except LevelDocumentError as exc:
        return emit_harness_error(exc, args=args, code="invalid_payload", reason=exc.code)
    from agent_runtime import paths
    from agent_runtime.level_sync import level_expectation_matches

    try:
        expect_provided, expect_sha256 = _level_expect_arg(args)
    except ValueError as exc:
        return emit_harness_error(exc, args=args, code="invalid_request")
    stored = store.read(workspace)
    # Checked on a dry run too: "would hermes take this document" and "is this
    # write still based on what is stored" are two different questions, and a
    # dry run that answered the first while silently ignoring the second would
    # promise a write that the real call refuses.
    if not level_expectation_matches(stored, expect_sha256, provided=expect_provided):
        return _level_conflict(args, workspace, stored)

    token = paths.safe_path_token(workspace)
    if getattr(args, "dry_run", False):
        row = _level_row(workspace, token, raw, full=False)
        # ``changed`` is answered against what is on disk RIGHT NOW, so a dry run
        # over an identical document says "nothing would change" instead of
        # implying a write.
        row["changed"] = stored != raw
        row["dry_run"] = True
        _print_stage42(attach_root_observability(_object_envelope("level", row)), args=args)
        return 0
    try:
        outcome = store.write(workspace, raw)
    except OSError as exc:
        return emit_harness_error(exc, args=args, code="runtime_unavailable")
    row = _level_row(workspace, token, raw, full=False)
    row["changed"] = bool(outcome["changed"])
    _print_stage42(attach_root_observability(_object_envelope("level", row)), args=args)
    return 0


#: The ``--expect-sha256`` word that means "there must be nothing stored", for
#: an argv lane that cannot spell JSON ``null``. The RPC lane says it with a
#: real ``null``; this is the same claim in the one vocabulary argv has.
LEVEL_EXPECT_ABSENT = "none"

#: Exit family 4 (conflict) — see ``ERROR_EXIT_CODES``. The RPC lane answers the
#: identical condition with ``ERR_CONFLICT`` / ``reason: sha256_mismatch``; one
#: refusal, one family across the two lanes.
LEVEL_CONFLICT_CODE = "level_sha256_mismatch"


def _level_expect_arg(args) -> tuple[bool, str | None]:
    """``(provided, sha)`` from ``--expect-sha256``, with argv's three states.

    Absent flag = unconditional; ``none`` = the level must be absent; a hex
    string = it must equal the stored bytes' sha256. A malformed token is
    refused as an invalid REQUEST rather than compared, because a comparison
    could only fail and a failed comparison is reported as a conflict — which
    would tell an operator with a typo that somebody else had written their
    level.
    """

    raw = getattr(args, "expect_sha256", None)
    if raw is None:
        return False, None
    token = str(raw).strip()
    if token.lower() in {LEVEL_EXPECT_ABSENT, "absent", "null"}:
        return True, None
    if len(token) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in token):
        raise ValueError(
            "--expect-sha256 takes 64 hex characters or 'none' (the level must be absent)"
        )
    return True, token


def _level_conflict(args, workspace_id: str, stored: bytes | None) -> int:
    """The compare-and-set refusal, in the exit taxonomy's words.

    The current sha rides the MESSAGE rather than a field of its own, because
    ``emit_harness_error`` carries ``code`` and ``reason`` and nothing else —
    and an operator's next move is to re-read the level anyway, which is where
    the authoritative bytes are.
    """

    from agent_runtime.level_sync import stored_level_sha256

    current = stored_level_sha256(stored) if stored is not None else None
    return emit_harness_error(
        ValueError(
            "the stored level is not the one this command was based on: "
            f"stored sha256 is {current or 'absent'} for {workspace_id}"
        ),
        args=args,
        code=LEVEL_CONFLICT_CODE,
        reason="sha256_mismatch",
    )


def _cmd_level_clear(args) -> int:
    """`harness level clear` — remove one workspace's level.

    The argv mirror of ``runtime.level.clear``, over the same store door and the
    same compare-and-set token, so an operator repairing by hand and the
    launcher's adapter cannot disagree about what "cleared" means.

    ``cleared: false`` for a workspace that had none is an accepted no-op, and a
    clear removes nothing from a REALM: the pull's ``upstream_absent`` arm is
    never a delete, so a level the realm still publishes comes back on the next
    pull.
    """

    store = _level_store()
    workspace = _level_workspace_for(args)
    if not workspace:
        return emit_harness_error(
            ValueError("no workspace selected; pass --workspace"), args=args, code="invalid_request"
        )
    from agent_runtime import paths
    from agent_runtime.level_sync import level_expectation_matches

    try:
        expect_provided, expect_sha256 = _level_expect_arg(args)
    except ValueError as exc:
        return emit_harness_error(exc, args=args, code="invalid_request")
    stored = store.read(workspace)
    if not level_expectation_matches(stored, expect_sha256, provided=expect_provided):
        return _level_conflict(args, workspace, stored)
    if getattr(args, "dry_run", False):
        row = {
            "workspace_id": workspace,
            "workspace_token": paths.safe_path_token(workspace),
            "cleared": stored is not None,
            "dry_run": True,
        }
        _print_stage42(attach_root_observability(_object_envelope("level", row)), args=args)
        return 0
    try:
        outcome = store.clear(workspace)
    except OSError as exc:
        return emit_harness_error(exc, args=args, code="runtime_unavailable")
    row = {
        "workspace_id": workspace,
        "workspace_token": paths.safe_path_token(workspace),
        "cleared": bool(outcome["changed"]),
    }
    _print_stage42(attach_root_observability(_object_envelope("level", row)), args=args)
    return 0
