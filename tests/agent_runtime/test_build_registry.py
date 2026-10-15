"""The announced-build registry (plan ``build-running-work-2026-10-04.md`` §2, row H3).

Record schema v1 with every key present (incl. ``unknowns``), temp-then-rename writes, the
reader's liveness / heartbeat / expiry rules, the registry directory under the
background-work home, the store-path authority and the core-cache fingerprint that must see
a record appear, and ``harness builds registry-path``.
"""

from __future__ import annotations

import json
import time
from argparse import Namespace

import pytest

from agent_runtime.builds import registry as reg
from agent_runtime.builds import vocabulary as v

NOW = 1_759_590_720.0


def _identity(verdict: str):
    verified = verdict == "verified"
    return lambda pid, start: (verdict not in ("dead",), verified, verdict)


def _record(**fields):
    base = {
        "job_id": "qb-1",
        "writer": {"pid": 4120, "host_start_time": 133412},
        "started_at": NOW - 60,
        "heartbeat_at": NOW - 10,
        "unknowns": [{"kind": "stage_line_unrecognized", "evidence": "Running Gradle task", "seen_at": NOW - 5}],
    }
    base.update(fields)
    return reg.new_record(**base)


def test_a_new_record_carries_every_v1_key_and_a_running_ttl():
    record = _record()
    assert set(record) == set(reg.RECORD_DEFAULTS)
    assert record["schema_version"] == v.REGISTRY_SCHEMA_VERSION == 1
    assert record["expires_at"] == NOW - 60 + v.RUNNING_RECORD_TTL_SECONDS
    finished = _record(finished_at=NOW, outcome="succeeded", expires_at=None)
    assert finished["expires_at"] == NOW + v.FINISHED_RECORD_TTL_SECONDS


def test_a_record_is_written_temp_then_rename_and_read_back(tmp_path):
    tmp_path = tmp_path / "registry"
    path = reg.write_record(tmp_path, _record())
    assert path == tmp_path / "qb-1.json"
    assert [p.name for p in tmp_path.iterdir()] == ["qb-1.json"]  # no temp left behind
    files, error = reg.read_records(tmp_path)
    assert error == ""
    assert [f.record["job_id"] for f in files] == ["qb-1"]
    assert files[0].record["unknowns"][0]["kind"] == "stage_line_unrecognized"
    with pytest.raises(ValueError):
        reg.write_record(tmp_path, _record(job_id="../escape"))


def test_an_absent_directory_is_zero_records_and_a_bad_file_is_typed(tmp_path):
    assert reg.read_records(tmp_path / "missing") == ([], "")
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "old.json").write_text(json.dumps({"schema_version": 0}), encoding="utf-8")
    files, error = reg.read_records(tmp_path)
    assert error == ""
    assert sorted((f.path.name, f.error) for f in files) == [("bad.json", "JSONDecodeError"), ("old.json", "schema_mismatch")]


@pytest.mark.parametrize(
    ("fields", "identity", "expected"),
    [
        ({}, "verified", ("live", None, "running")),
        ({"heartbeat_at": NOW - 130}, "verified", ("live", None, "stalling")),
        ({"heartbeat_at": NOW - 300}, "verified", ("stalled", None, "stalled")),
        ({"status": "queued", "heartbeat_at": NOW - 3000}, "verified", ("live", None, "running")),
        ({}, "dead", ("dead", "lost", "error")),
        ({}, "recycled", ("dead", "lost", "error")),
        ({}, "start_time_unreadable", ("unknown", None, "unknown")),
        ({"outcome": "succeeded", "finished_at": NOW}, "dead", ("dead", "succeeded", "completed")),
        ({"outcome": "failed", "finished_at": NOW}, "dead", ("dead", "failed", "error")),
    ],
)
def test_the_reader_rules(fields, identity, expected):
    verdict = reg.evaluate(_record(**fields), now=NOW, pid_identity=_identity(identity))
    assert (verdict.liveness, verdict.outcome, verdict.status) == expected
    assert verdict.expired is False


def test_a_lost_build_is_kept_until_it_expires_and_an_unproven_writer_is_unidentified():
    lost = reg.evaluate(_record(), now=NOW, pid_identity=_identity("dead"))
    assert lost.outcome == "lost" and not lost.expired
    expired = reg.evaluate(_record(expires_at=NOW - 1), now=NOW, pid_identity=_identity("verified"))
    assert expired.expired
    unproven = reg.evaluate(_record(), now=NOW, pid_identity=_identity("no_baseline"))
    assert unproven.writer_identified is False


def test_the_reader_words_are_the_running_work_words():
    """Enumerated from the thing itself: the registry may not import running_work (it imports this)."""

    from agent_runtime.running_work import vocabulary as rw

    assert (reg.STATUS_RUNNING, reg.STATUS_STALLING, reg.STATUS_STALLED, reg.STATUS_COMPLETED, reg.STATUS_ERROR,
            reg.STATUS_UNKNOWN) == (rw.STATUS_RUNNING, rw.STATUS_STALLING, rw.STATUS_STALLED, rw.STATUS_COMPLETED,
                                    rw.STATUS_ERROR, rw.STATUS_UNKNOWN)
    assert reg._DISPROVEN == {rw.PID_DEAD, rw.PID_RECYCLED}
    assert reg.STALLING_FRACTION == rw.STALLING_FRACTION


def test_gc_removes_only_records_past_expiry_plus_grace(tmp_path):
    tmp_path = tmp_path / "registry"
    reg.write_record(tmp_path, _record(job_id="old", expires_at=NOW - 100))
    reg.write_record(tmp_path, _record(job_id="fresh", expires_at=NOW + 100))
    reg.stop_request_path(tmp_path, "old").write_text("", encoding="utf-8")
    assert reg.gc_expired(tmp_path, now=NOW, grace_seconds=50) == ["old"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fresh.json"]


def test_the_registry_lives_under_the_background_work_home_and_joins_the_store_paths():
    from agent_runtime.profile_home import get_hermes_background_work_home
    from agent_runtime.running_work import running_work_store_paths

    assert reg.registry_dir() == get_hermes_background_work_home() / "builds"
    paths = running_work_store_paths()
    assert reg.registry_dir() in paths
    assert paths[-1].name == "state.db"


def test_the_core_cache_fingerprint_stats_every_record(monkeypatch):
    from agent_runtime.core_cache import fingerprint as fp

    def collected():
        entries = []
        assert fp._collect_running_work(entries)
        return {entry.path: (entry.mtime_ns, entry.size) for entry in entries}

    before = collected()
    record = reg.write_record(reg.registry_dir(), _record())
    after = collected()
    assert str(record) in after and str(record) not in before
    time.sleep(0.02)
    reg.write_record(reg.registry_dir(), _record(stage="linking", stage_detail="error LNK2019: unresolved"))
    assert collected()[str(record)] != after[str(record)]


def test_registry_path_verb_prints_the_reader_directory(capsys):
    from hermes_cli.harness_parts.builds_commands import _cmd_builds_registry_path

    assert _cmd_builds_registry_path(Namespace(json=True, output="json")) == 0
    printed = json.loads(capsys.readouterr().out)
    body = printed.get("data") or printed
    assert body["registry_dir"] == str(reg.registry_dir())
    assert body["env"] == "HERMES_BUILD_REGISTRY_DIR"
