"""One-shot startup rewrite of the retired provider id ``local-llama-hermes`` to ``llamacpp``.

Owner ruling 2026-09-29: a one-shot rewrite at hermes startup covering every store and the
user's ``config.yaml``, reporting what changed; then the alias is dropped
(``PROVIDER_ID_ALIASES`` no longer reads the old id, so a row left carrying it would route
its turns to the cloud resolver). The places the id can sit:

* persona definitions — ``<store>/agents/*.json`` (the roster's store tier);
* persona instance rows — ``<store>/persona_instances*/**.json`` (the instance override tier);
* chat-session overrides — ``state.db`` ``sessions.model_config``
  (``mission_control_chat_model_override.provider``, ``mission-chat --provider``);
* the user's ``config.yaml`` — any ``*provider:`` scalar (persona overrides,
  ``agent_runtime.default_provider``, ``model.provider``).

Every changed file is copied first into ``<home>/backups/local-llama-legacy-id-<stamp>/``
(the database through SQLite's online backup), every rewrite is logged at WARNING, and the
report is written to ``<store>/migrations/local_llama_legacy_id.json``, whose presence makes
the next start a single stat. JSON and YAML are rewritten textually so their formatting and
comments survive. Fail-open: a store that cannot be read is reported, never raised.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import PROVIDER_ID

__layer__ = "stores"

logger = logging.getLogger(__name__)

#: The retired id. Kept only here: nothing else reads it once the alias is dropped.
RETIRED_PROVIDER_ID = "local-llama-hermes"
MARKER_NAME = "local_llama_legacy_id.json"
_CHAT_OVERRIDE_KEY = "mission_control_chat_model_override"
_JSON_PROVIDER_RE = re.compile(r'("provider"\s*:\s*)"' + re.escape(RETIRED_PROVIDER_ID) + '"')
_YAML_PROVIDER_RE = re.compile(
    r"^(\s*(?:-\s+)?[A-Za-z_]*provider\s*:\s*)(['\"]?)" + re.escape(RETIRED_PROVIDER_ID) + r"\2(?=\s*(?:#.*)?$)",
    re.MULTILINE,
)


def marker_path(store_root: Path) -> Path:
    return store_root / "migrations" / MARKER_NAME


def migrate_retired_provider_id_once() -> dict[str, Any] | None:
    """Run the rewrite for the active home unless its marker says it already ran.

    Returns the report when it ran, ``None`` when the marker was already there."""
    from hermes_constants import get_hermes_home

    from .. import paths

    store_root = paths.store_root()
    if marker_path(store_root).exists():
        return None
    report = rewrite_retired_provider_id(home=get_hermes_home(), store_root=store_root)
    if store_root.is_dir():  # never create a store for a home that has none
        marker = marker_path(store_root)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def rewrite_retired_provider_id(*, home: Path, store_root: Path) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = _Run(home=Path(home), backup_dir=Path(home) / "backups" / f"local-llama-legacy-id-{stamp}")
    for directory in (store_root / "agents", store_root / "persona_instances",
                      store_root / "persona_instances_archive"):
        if directory.is_dir():
            for path in sorted(directory.rglob("*.json")):
                run.json_row(path)
    run.config_yaml(Path(home) / "config.yaml")
    run.state_db(Path(home) / "state.db")
    return {
        "schema": "hermes.local_llama.legacy_id_migration/v1",
        "from": RETIRED_PROVIDER_ID,
        "to": PROVIDER_ID,
        "ran_at": stamp,
        "rewritten": run.rewritten,
        "backup_dir": str(run.backup_dir) if run.rewritten else None,
        "errors": run.errors,
    }


class _Run:
    def __init__(self, *, home: Path, backup_dir: Path) -> None:
        self.home = home
        self.backup_dir = backup_dir
        self.rewritten: list[dict[str, Any]] = []
        self.errors: list[dict[str, str]] = []

    def _backup_target(self, path: Path) -> Path:
        try:
            relative = path.resolve().relative_to(self.home.resolve())
        except ValueError:
            relative = Path(path.name)
        target = self.backup_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _record(self, path: Path, kind: str, count: int, backup: Path) -> None:
        self.rewritten.append({"path": str(path), "kind": kind, "count": count, "backup": str(backup)})
        logger.warning("local_llama_legacy_id_rewritten kind=%s path=%s count=%d backup=%s from=%s to=%s",
                       kind, path, count, backup, RETIRED_PROVIDER_ID, PROVIDER_ID)

    def _error(self, path: Path, exc: Exception) -> None:
        self.errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
        logger.warning("local_llama_legacy_id_rewrite_failed path=%s error=%s", path, exc)

    def _rewrite_text(self, path: Path, kind: str, pattern: re.Pattern, validate) -> None:
        try:
            text = path.read_text(encoding="utf-8")
            if RETIRED_PROVIDER_ID not in text:
                return
            new_text, count = pattern.subn(lambda m: m.group(1) + _quoted(m, PROVIDER_ID), text)
            if not count:
                return
            validate(new_text)
            backup = self._backup_target(path)
            shutil.copy2(path, backup)
            path.write_text(new_text, encoding="utf-8")
        except Exception as exc:
            self._error(path, exc)
            return
        self._record(path, kind, count, backup)

    def json_row(self, path: Path) -> None:
        self._rewrite_text(path, "json_row", _JSON_PROVIDER_RE, json.loads)

    def config_yaml(self, path: Path) -> None:
        if not path.is_file():
            return

        def _validate(text: str) -> None:
            from agent_runtime import yaml_io

            yaml_io.load(text)  # parse check only; the rewrite itself stays textual

        self._rewrite_text(path, "config_yaml", _YAML_PROVIDER_RE, _validate)

    def state_db(self, path: Path) -> None:
        if not path.is_file():
            return
        try:
            conn = sqlite3.connect(str(path), timeout=10)
        except Exception as exc:
            self._error(path, exc)
            return
        try:
            try:
                rows = conn.execute(
                    "SELECT id, model_config FROM sessions WHERE model_config LIKE ?",
                    (f"%{RETIRED_PROVIDER_ID}%",),
                ).fetchall()
            except sqlite3.OperationalError:  # no sessions table: nothing stored here
                return
            updates = []
            for session_id, raw in rows:
                config = json.loads(raw or "{}")
                override = config.get(_CHAT_OVERRIDE_KEY)
                if isinstance(override, dict) and override.get("provider") == RETIRED_PROVIDER_ID:
                    override["provider"] = PROVIDER_ID
                    updates.append((json.dumps(config, sort_keys=True, separators=(",", ":")), session_id))
            if not updates:
                return
            backup = self._backup_target(path)
            with sqlite3.connect(str(backup)) as copy:
                conn.backup(copy)
            copy.close()
            with conn:
                conn.executemany("UPDATE sessions SET model_config = ? WHERE id = ?", updates)
        except Exception as exc:
            self._error(path, exc)
            return
        finally:
            conn.close()
        self._record(path, "state_db_chat_override", len(updates), backup)


def _quoted(match: re.Match, value: str) -> str:
    quote = match.group(2) if match.re is _YAML_PROVIDER_RE else '"'
    return f"{quote}{value}{quote}"
