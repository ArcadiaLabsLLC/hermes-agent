"""Revision-checked, install-local table/preset definitions in an explicit DB.

No implicit HERMES_HOME lookup, global connection, worker or model execution.
This is authoring persistence, NOT room admission: the room service fences
edits/deletes against active runs inside this same write transaction. The
``runtime.discussion.table.*`` and ``preset.*`` methods registered by
``agent_runtime.discussions.rpc`` reach this store only through that service.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from gateway.hosted_rooms_common import connect
from hermes_cli.sqlite_util import transaction

from .definitions import (
    MAX_REVISION, Configuration, DefinitionError, PresetSpec, TableSpec,
    apply_preset, fields, identifier, revision,
)

__layer__ = "stores"

_SCHEMA_VERSION = 1
_PARSERS = {"table": TableSpec.parse, "preset": PresetSpec.parse}


class DefinitionKind(StrEnum):
    TABLE = "table"
    PRESET = "preset"


@dataclass(frozen=True, slots=True)
class PresetOrigin:
    """The loaded revision, retained even after rename/update/delete of its source.

    This configuration is an edit baseline, not a second writable preset. It
    makes Revert and Modified deterministic while other consoles edit the source.
    """
    preset_id: str
    revision: int
    configuration: Configuration

    def to_dict(self) -> dict[str, Any]:
        return {"preset_id": self.preset_id, "revision": self.revision,
                "configuration": self.configuration.to_dict()}

    @classmethod
    def parse(cls, value: Any) -> PresetOrigin:
        value = fields(value, {"preset_id", "revision", "configuration"}, field="preset_origin")
        return cls(identifier(value["preset_id"], "preset_id"),
                   revision(value["revision"], "preset_revision", minimum=1),
                   Configuration.parse(value["configuration"]))


@dataclass(frozen=True, slots=True)
class DefinitionRecord:
    kind: DefinitionKind
    workspace_id: str
    definition_id: str
    revision: int
    spec: TableSpec | PresetSpec
    preset_origin: PresetOrigin | None = None

    @property
    def preset_modified(self) -> bool:
        return self.preset_origin is not None and self.spec.configuration != self.preset_origin.configuration

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "workspace_id": self.workspace_id, "definition_id": self.definition_id,
                "revision": self.revision, "spec": self.spec.to_dict(),
                "preset_origin": self.preset_origin.to_dict() if self.preset_origin is not None else None,
                "preset_modified": self.preset_modified}


@dataclass(frozen=True, slots=True)
class DefinitionPage:
    records: tuple[DefinitionRecord, ...]
    next_cursor: str | None


def _encode(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _schema_ready(conn: sqlite3.Connection) -> bool:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mc_discussion_schema'").fetchone() is None:
        return False
    rows = conn.execute("SELECT version FROM mc_discussion_schema").fetchall()
    if len(rows) != 1 or rows[0][0] != _SCHEMA_VERSION:
        raise DefinitionError("unsupported_schema", "discussion_definitions")
    return True


def _initialize(conn: sqlite3.Connection) -> None:
    if _schema_ready(conn):  # Recheck AFTER acquiring the IMMEDIATE schema lock.
        return
    # No user_version: SessionDB and the upstream hosted-room store own their
    # own migrations in this same file. DDL + version are committed atomically.
    conn.execute("CREATE TABLE mc_discussion_schema (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL)")
    conn.execute("""CREATE TABLE mc_discussion_definitions (
        kind TEXT NOT NULL CHECK(kind IN ('table','preset')),
        workspace_id TEXT NOT NULL,
        definition_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision > 0 AND revision <= 9007199254740991),
        document TEXT NOT NULL,
        preset_origin TEXT,
        deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)),
        PRIMARY KEY(kind, workspace_id, definition_id)
    )""")
    conn.execute("INSERT INTO mc_discussion_schema(singleton, version) VALUES (1, ?)", (_SCHEMA_VERSION,))


def _key(kind: DefinitionKind | str, workspace_id: str, definition_id: str) -> tuple[str, str, str]:
    try:
        normalized = DefinitionKind(kind).value
    except (TypeError, ValueError) as exc:
        raise DefinitionError("invalid_kind", "kind") from exc
    return normalized, identifier(workspace_id, "workspace_id"), identifier(definition_id, "definition_id")


def _raw(conn: sqlite3.Connection, key: tuple[str, str, str]) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM mc_discussion_definitions WHERE kind=? AND workspace_id=? AND definition_id=?", key,
    ).fetchone()


def _record(row: sqlite3.Row) -> DefinitionRecord:
    if row["deleted"]:
        raise DefinitionError("definition_deleted", "definition_id", current_revision=row["revision"])
    try:
        kind = DefinitionKind(row["kind"])
        origin = PresetOrigin.parse(json.loads(row["preset_origin"])) if row["preset_origin"] is not None else None
        if origin is not None and kind != DefinitionKind.TABLE:
            raise DefinitionError("invalid_origin", "preset_origin")
        return DefinitionRecord(kind, identifier(row["workspace_id"], "workspace_id"),
                                identifier(row["definition_id"], "definition_id"),
                                revision(row["revision"], "revision", minimum=1),
                                _PARSERS[kind.value](json.loads(row["document"])), origin)
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        # Corruption is not an empty roster/table list; fail visibly.
        raise DefinitionError("corrupt_definition", "definition_id") from exc


def _required(conn: sqlite3.Connection, key: tuple[str, str, str]) -> DefinitionRecord:
    row = _raw(conn, key)
    if row is None:
        raise DefinitionError("definition_not_found", "definition_id")
    return _record(row)


def _expect(record: DefinitionRecord, expected: int) -> None:
    if record.revision != expected:
        raise DefinitionError("stale_revision", "expect_revision", current_revision=record.revision)


def _next_revision(current: int) -> int:
    if current >= MAX_REVISION:
        raise DefinitionError("revision_exhausted", "revision")
    return current + 1


def _assert_table_editable(conn: sqlite3.Connection, key: tuple[str, str, str]) -> None:
    if key[0] != "table":
        return
    # The optional run schema may not exist in a pure authoring-only client.
    # Checking and writing are inside the SAME immediate transaction as Start.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='mc_discussion_table_claims'").fetchone():
        if conn.execute("SELECT 1 FROM mc_discussion_table_claims WHERE workspace_id=? AND table_id=?", key[1:]).fetchone():
            raise DefinitionError("table_busy", "definition_id")


def _write(conn: sqlite3.Connection, key: tuple[str, str, str], spec: TableSpec | PresetSpec,
           *, expected: int, origin: PresetOrigin | None = None) -> DefinitionRecord:
    _assert_table_editable(conn, key)
    row = _raw(conn, key)
    if row is None:
        if expected != 0:
            raise DefinitionError("definition_not_found", "definition_id")
        new_revision = 1
        conn.execute(
            "INSERT INTO mc_discussion_definitions(kind,workspace_id,definition_id,revision,document,preset_origin) VALUES(?,?,?,?,?,?)",
            (*key, new_revision, _encode(spec.to_dict()), _encode(origin.to_dict()) if origin is not None else None),
        )
    else:
        _expect(_record(row), expected)
        new_revision = _next_revision(expected)
        conn.execute(
            "UPDATE mc_discussion_definitions SET revision=?,document=?,preset_origin=? WHERE kind=? AND workspace_id=? AND definition_id=? AND revision=? AND deleted=0",
            (new_revision, _encode(spec.to_dict()), _encode(origin.to_dict()) if origin is not None else None, *key, expected),
        )
    return DefinitionRecord(DefinitionKind(key[0]), key[1], key[2], new_revision, spec, origin)


class DefinitionStore:
    """Small per-operation connections using the repository's shared SQLite stack.

    Construct with the runtime's explicitly captured absolute database path.
    Schema initialization happens on first operation, never at import/construction.
    The owning service must not accept this path from an untrusted RPC request.
    """

    def __init__(self, db_path: Path | str) -> None:
        path = Path(db_path)
        if not path.is_absolute() or ".." in path.parts:
            raise DefinitionError("absolute_database_path_required", "db_path")
        self._db_path = path

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path, db_label="discussion-definitions", ready=_schema_ready,
                       initialize=_initialize, lock_retries=4)

    def get(self, kind: DefinitionKind | str, workspace_id: str, definition_id: str) -> DefinitionRecord:
        key = _key(kind, workspace_id, definition_id)
        with closing(self._connect()) as conn:
            return _required(conn, key)

    def list(self, kind: DefinitionKind | str, workspace_id: str, *, limit: int = 50,
             after: str | None = None) -> DefinitionPage:
        # Keyset pagination remains bounded even if other consoles mutate rows.
        kind_value, workspace, _ = _key(kind, workspace_id, "list")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise DefinitionError("invalid_limit", "limit")
        cursor = identifier(after, "after") if after is not None else ""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM mc_discussion_definitions WHERE kind=? AND workspace_id=? AND deleted=0 AND definition_id>? ORDER BY definition_id LIMIT ?",
                (kind_value, workspace, cursor, limit + 1),
            ).fetchall()
            records = tuple(_record(row) for row in rows[:limit])
            return DefinitionPage(records, records[-1].definition_id if len(rows) > limit else None)

    def save_table(self, workspace_id: str, table_id: str, value: Mapping[str, Any] | TableSpec,
                   *, expect_revision: int) -> DefinitionRecord:
        key = _key(DefinitionKind.TABLE, workspace_id, table_id)
        expected = revision(expect_revision)
        spec = TableSpec.parse(value.to_dict() if isinstance(value, TableSpec) else value)
        with transaction(self._connect(), immediate=True) as conn:
            existing = _raw(conn, key)
            # Ordinary edits retain the originally loaded recipe. Only load_preset
            # may change that baseline; Update of the source cannot affect it.
            origin = _record(existing).preset_origin if existing is not None else None
            return _write(conn, key, spec, expected=expected, origin=origin)

    def save_preset(self, workspace_id: str, preset_id: str, value: Mapping[str, Any] | PresetSpec,
                    *, expect_revision: int) -> DefinitionRecord:
        key = _key(DefinitionKind.PRESET, workspace_id, preset_id)
        expected = revision(expect_revision)
        spec = PresetSpec.parse(value.to_dict() if isinstance(value, PresetSpec) else value)
        with transaction(self._connect(), immediate=True) as conn:
            return _write(conn, key, spec, expected=expected)

    def delete(self, kind: DefinitionKind | str, workspace_id: str, definition_id: str,
               *, expect_revision: int) -> int:
        key = _key(kind, workspace_id, definition_id)
        expected = revision(expect_revision, minimum=1)
        with transaction(self._connect(), immediate=True) as conn:
            record = _required(conn, key)
            _expect(record, expected)
            _assert_table_editable(conn, key)
            new_revision = _next_revision(expected)
            conn.execute(
                "UPDATE mc_discussion_definitions SET revision=?,deleted=1 WHERE kind=? AND workspace_id=? AND definition_id=? AND revision=?",
                (new_revision, *key, expected),
            )
            # Keep the tombstone: an old create retry cannot resurrect this ID.
            return new_revision

    def load_preset(self, workspace_id: str, table_id: str, preset_id: str,
                    *, expect_table_revision: int, expect_preset_revision: int) -> DefinitionRecord:
        table_key = _key(DefinitionKind.TABLE, workspace_id, table_id)
        preset_key = _key(DefinitionKind.PRESET, workspace_id, preset_id)
        expected = revision(expect_table_revision, minimum=1)
        preset_expected = revision(expect_preset_revision, "expect_preset_revision", minimum=1)
        with transaction(self._connect(), immediate=True) as conn:
            table, preset = _required(conn, table_key), _required(conn, preset_key)
            _expect(table, expected)
            if preset.revision != preset_expected:
                raise DefinitionError("stale_preset_revision", "expect_preset_revision", current_revision=preset.revision)
            candidate = apply_preset(table.spec, preset.spec)
            origin = PresetOrigin(preset_id, preset.revision, preset.spec.configuration)
            return _write(conn, table_key, candidate, expected=expected, origin=origin)

    def custom_table(self, workspace_id: str, table_id: str, *, expect_revision: int) -> DefinitionRecord:
        """Detach the loaded recipe without changing the table or its team."""
        key = _key(DefinitionKind.TABLE, workspace_id, table_id)
        expected = revision(expect_revision, minimum=1)
        with transaction(self._connect(), immediate=True) as conn:
            current = _required(conn, key)
            _expect(current, expected)
            return _write(conn, key, current.spec, expected=expected)

    def revert_table(self, workspace_id: str, table_id: str, *, expect_revision: int) -> DefinitionRecord:
        key = _key(DefinitionKind.TABLE, workspace_id, table_id)
        expected = revision(expect_revision, minimum=1)
        with transaction(self._connect(), immediate=True) as conn:
            current = _required(conn, key)
            _expect(current, expected)
            if current.preset_origin is None:
                raise DefinitionError("no_loaded_preset", "preset_origin")
            candidate = TableSpec.parse(replace(current.spec, configuration=current.preset_origin.configuration).to_dict())
            return _write(conn, key, candidate, expected=expected, origin=current.preset_origin)
