"""Cases for the statements no charsheet test reached (COLD in
``scripts/unreachable_branch_report.py``, runtime-queue row, w5-rt 2026-10-02).

Each arm is a failure path a real host produces — a corrupt file, a lock whose
mtime vanished between read and stat, a full disk under the holder record, a
replace that fails mid-write — so each is given a case rather than deleted.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from agent.charsheet import draft_lock
from agent.charsheet import revisions as revisions_module
from agent.charsheet.draft import DRAFT_FILENAME, CharacterDraft, drafts_dir
from agent.charsheet.revisions import STATE_FILENAME, ImageRevisionStore


@pytest.fixture(autouse=True)
def _hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))


def _write_draft(draft_id: str, text: str) -> None:
    directory = drafts_dir() / draft_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / DRAFT_FILENAME).write_text(text, encoding="utf-8")


# ── agent/charsheet/draft/draft.py ─────────────────────────────────────────


def test_a_draft_file_that_is_not_json_is_named_corrupt():
    _write_draft("d_bad", "{not json")
    with pytest.raises(ValueError, match="corrupt draft file"):
        CharacterDraft.load("d_bad")


def test_list_drafts_skips_an_unreadable_draft_and_keeps_the_rest(caplog):
    _write_draft("d_bad", "{not json")
    _write_draft("d_ok", json.dumps({"id": "d_ok"}))
    with caplog.at_level(logging.WARNING):
        listed = CharacterDraft.list_drafts()
    assert [draft.directory.name for draft in listed] == ["d_ok"]
    assert "skipping unreadable draft d_bad" in caplog.text


# ── agent/charsheet/draft_lock.py ──────────────────────────────────────────


def test_a_holder_whose_lock_vanished_before_stat_reads_age_zero(tmp_path, monkeypatch):
    lock = tmp_path / "gen.lock"
    lock.write_text(json.dumps({"pid": 7}), encoding="utf-8")
    real_stat = Path.stat

    def stat(self, *args, **kwargs):
        if self == lock:
            raise FileNotFoundError(str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    holder = draft_lock._read_holder(lock)
    assert holder["pid"] == 7 and holder["age_seconds"] == 0.0


def test_a_claim_whose_holder_record_cannot_be_written_still_holds(tmp_path, monkeypatch, caplog):
    lock = tmp_path / "gen.lock"

    def dump(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(draft_lock.json, "dump", dump)
    with caplog.at_level(logging.WARNING):
        assert draft_lock._claim(lock, {"pid": 1}) is True
    assert lock.is_file()
    assert "holder record not written" in caplog.text
    assert draft_lock._claim(lock, {"pid": 2}) is False  # positive control: the claim excludes


# ── agent/charsheet/revisions.py ───────────────────────────────────────────


def _failing_replace(monkeypatch, *, target_name: str):
    real_replace = os.replace

    def replace(src, dst, *args, **kwargs):
        if Path(dst).name == target_name:
            raise OSError("replace failed")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(revisions_module.os, "replace", replace)


def _debris(root: Path) -> list[str]:
    return sorted(p.name for p in root.rglob("*") if p.is_file() and p.name.endswith(revisions_module._TMP_SUFFIX))


def test_a_state_write_that_fails_leaves_no_temp_file(tmp_path, monkeypatch):
    source = tmp_path / "a.png"
    source.write_bytes(b"a")
    store = ImageRevisionStore(tmp_path / "rev")
    _failing_replace(monkeypatch, target_name=STATE_FILENAME)
    with pytest.raises(OSError, match="replace failed"):
        store.propose("row@walk@e", source, note="n")
    assert _debris(tmp_path / "rev") == []


def test_an_image_copy_that_fails_leaves_no_temp_file(tmp_path, monkeypatch):
    source = tmp_path / "a.png"
    source.write_bytes(b"a")
    store = ImageRevisionStore(tmp_path / "rev")
    real_replace = os.replace

    def replace(src, dst, *args, **kwargs):
        if Path(dst).name != STATE_FILENAME:
            raise OSError("replace failed")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(revisions_module.os, "replace", replace)
    with pytest.raises(OSError, match="replace failed"):
        store.propose("row@walk@e", source, note="n")
    assert _debris(tmp_path / "rev") == []


# ── agent/charsheet/draft/ package (draft.py was split into it) ────────────

from types import SimpleNamespace  # noqa: E402

from agent.charsheet import _support  # noqa: E402
from agent.charsheet.draft import DRAFTS_DIRNAME, MANIFEST_FILENAME, SHEET_FILENAME, characters_dir, migrate_characters_home, sprite_payload  # noqa: E402
from agent.charsheet.draft import migration as migration_module  # noqa: E402
from agent.charsheet.draft.compose import Composer  # noqa: E402
from agent.charsheet.draft.installed import sheet_revision  # noqa: E402


def _old_store(tmp_path: Path) -> Path:
    source = tmp_path / "old" / "characters"
    bad_draft = source / DRAFTS_DIRNAME / "d_corrupt"
    bad_draft.mkdir(parents=True)
    (bad_draft / DRAFT_FILENAME).write_text("{not json", encoding="utf-8")
    installed = source / "hero"
    installed.mkdir(parents=True)
    (installed / MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")
    return source


def test_migration_moves_unreadable_entries_under_their_directory_names(tmp_path):
    source = _old_store(tmp_path)
    receipt = migrate_characters_home(source, tmp_path / "shared", source_home="old")
    moved = {(row["kind"], row["id"] if row["kind"] == "draft" else row.get("slug")) for row in receipt["moved"]}
    assert ("draft", "d_corrupt") in moved  # the id fell back to the directory name
    assert receipt["stamped"] == []  # an unreadable draft.json is never stamped
    assert any(row["kind"] == "installed" for row in receipt["moved"])  # a corrupt manifest still moves


def test_migration_reports_an_entry_it_could_not_move_and_carries_on(tmp_path, monkeypatch):
    source = _old_store(tmp_path)

    def replace(_src, _dst, *args, **kwargs):
        raise OSError("locked")

    monkeypatch.setattr(migration_module.os, "replace", replace)
    receipt = migrate_characters_home(source, tmp_path / "shared", source_home="old")
    assert receipt["moved"] == []
    assert {row["reason"] for row in receipt["skipped"]} == {"could not move: locked"}
    assert len(receipt["skipped"]) == 2


def test_the_revision_of_a_missing_sheet_is_empty(tmp_path):
    assert sheet_revision(tmp_path / "absent.webp") == ""


def test_an_installed_character_with_a_corrupt_manifest_is_named_corrupt():
    directory = characters_dir() / "hero"
    directory.mkdir(parents=True)
    (directory / MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")
    (directory / SHEET_FILENAME).write_bytes(b"x")
    with pytest.raises(ValueError, match="corrupt manifest"):
        sprite_payload("hero")


def test_a_corrupt_prior_manifest_does_not_block_composing_over_the_slug():
    directory = characters_dir() / "hero"
    directory.mkdir(parents=True)
    (directory / MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")
    composer = Composer(SimpleNamespace(slug="hero", id="d_new"))
    assert composer._guard_slug() == directory
    # Positive control: a readable manifest from another draft refuses.
    (directory / MANIFEST_FILENAME).write_text(json.dumps({"draftId": "d_other"}), encoding="utf-8")
    with pytest.raises(ValueError, match="already installed from draft d_other"):
        composer._guard_slug()


# ── agent/charsheet/_support.py ────────────────────────────────────────────


@pytest.mark.parametrize("write", [
    lambda path: _support.write_json_atomic(path, {"a": 1}),
    lambda path: _support.write_bytes_atomic(path, b"a"),
])
def test_an_atomic_write_that_fails_leaves_no_temp_file(tmp_path, monkeypatch, write):
    def replace(_src, _dst, *args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(_support.os, "replace", replace)
    with pytest.raises(OSError, match="replace failed"):
        write(tmp_path / "out" / "f.json")
    assert list((tmp_path / "out").iterdir()) == []
