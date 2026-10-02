# Workspace LEVEL CLI tier: `hermes harness level …`.
#
# This module shares the Stage-42 envelope/printer/error helpers
# with every other tier — imported from hermes_cli.harness_support below, not
# inherited. Both writes go through the LevelStore chokepoint, the same door
# realm sync's pull applier uses.
#
# THE CONTRACT: the launcher owns the level document's format and hermes owns
# its transport. `show --full` hands the stored bytes back VERBATIM. The argv
# writers (`level set`, `level clear`) were deleted 2026-10-02 (owner ruling:
# the launcher calls them only as `runtime.level.set` / `runtime.level.clear`,
# no operator or script uses the argv form); the read stays for operators.
#
# Design contract: EterniaLauncher
# docs/spatial/planned/one-engine-one-catalogue-levels-per-workspace.md (R15).

# A real module (lane H1, 2026-09-24): it imports everything it reads, and a
# test patches a name HERE, where this module looks it up — never on
# ``hermes_cli.harness`` (W0-G4, tests/tooling/test_harness_namespace_is_thin.py).

from __future__ import annotations


from agent_runtime.root_observability import attach_root_observability
from agent_runtime.store import WorkspaceStore
from hermes_cli.harness_support import (
    _object_envelope,
    _print_stage42,
    emit_harness_error,
)

__layer__ = "lanes"
__all__ = [
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
