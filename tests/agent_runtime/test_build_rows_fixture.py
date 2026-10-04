"""The build-row golden both sides pin (plan ``build-running-work-2026-10-04.md`` §1, row H4).

``tests/fixtures/builds/build_rows.json`` is WRITTEN by the producer from a seeded home
(``_build_rows_fixture.py``); this file proves the bytes are the producer's, and that the
golden exercises every word of every build vocabulary — enumerated from the vocabulary
tuples themselves, never from a literal typed beside them. The launcher mirrors the file and
round-trips every arm.
"""

from __future__ import annotations

import json

from agent_runtime.builds import unknowns as u
from agent_runtime.builds import vocabulary as v

from tests.agent_runtime import _build_rows_fixture as fx

#: Words only the DETECTED source produces; it lands in row H6, which empties this set.
DETECTED_ONLY = {"source": {v.SOURCE_DETECTED}, "started_by": {v.STARTED_BY_EXTERNAL},
                 "progress_signal": {v.PROGRESS_SIGNAL_CPU}, "reason": {v.CONTROL_REASON_SLOT_UNBOUND}}


def _golden() -> dict:
    return json.loads(fx.FIXTURE_PATH.read_text(encoding="utf-8"))


def test_the_golden_is_the_producers_bytes(tmp_path):
    assert fx.render(fx.produce(tmp_path)) == fx.FIXTURE_PATH.read_text(encoding="utf-8")


def _words(rows: list[dict], read) -> set:
    return {word for row in rows for word in read(row) if word is not None}


def test_every_vocabulary_word_appears_in_the_golden():
    rows = _golden()["rows"]
    expected = {
        "source": (lambda r: [r["source"]], set(v.BUILD_SOURCES) - DETECTED_ONLY["source"]),
        "liveness": (lambda r: [r["liveness"]], set(v.BUILD_LIVENESS)),
        "outcome": (lambda r: [r["outcome"]], set(v.BUILD_OUTCOMES)),
        "stage": (lambda r: [r["stage"]], set(v.BUILD_STAGES)),
        "toolchain": (lambda r: [r["toolchain"]], set(v.BUILD_TOOLCHAINS)),
        "mode": (lambda r: [r["mode"]], set(v.BUILD_MODES)),
        "started_by": (lambda r: [r["started_by"]["kind"]], set(v.STARTED_BY_KINDS) - DETECTED_ONLY["started_by"]),
        "progress_signal": (lambda r: [r["progress_signal"]], set(v.PROGRESS_SIGNALS) - DETECTED_ONLY["progress_signal"]),
        "control": (lambda r: [r["controls"]["stop"], r["controls"]["restart"]], set(v.CONTROL_STATES)),
        "reason": (lambda r: [r["controls"]["stop_reason"] or None, r["controls"]["restart_reason"] or None],
                   set(v.CONTROL_REASONS) - DETECTED_ONLY["reason"]),
        "env_source": (lambda r: [v.ENV_SOURCE_SLOT_PREFIX if r["env_source"].startswith(v.ENV_SOURCE_SLOT_PREFIX)
                                  else r["env_source"]], set(v.ENV_SOURCE_ARMS)),
        "unknown": (lambda r: [entry["kind"] for entry in r["unknowns"]], set(u.UNKNOWN_KINDS)),
        "artifact": (lambda r: [(r["artifact"] or {}).get("kind")], set(v.ARTIFACT_KINDS)),
    }
    for name, (read, words) in expected.items():
        assert _words(rows, read) == words, name


def test_every_row_carries_every_build_key_and_the_sources_name_each_sub():
    golden = _golden()
    keys = set(golden["rows"][0])
    assert all(set(row) == keys for row in golden["rows"])
    assert {"workspace_id", "slot_id", "env_source", "started_by_instance", "unknowns", "controls"} <= keys
    build = golden["sources"]["build"]
    assert set(build["sub"]) == set(v.BUILD_SOURCES)
    assert {"scan_ms", "processes_examined", "candidates", "budget_ms"} <= set(build["sub"]["detected"])
    announced = golden["source_variants"]["registry_unreadable"]["sub"]["announced"]
    assert announced["reason"] in v.ANNOUNCED_SUB_REASONS


def test_a_build_row_names_its_starter_or_says_it_could_not():
    by_id = {row["work_id"]: row for row in _golden()["rows"]}
    owned = by_id["build:agent:sess_build_live"]
    assert (owned["started_by_instance"], owned["workspace_id"], owned["slot_id"]) == (
        "personainst_dev_frontend", "ws_team", "launcher")
    orphan = by_id["build:agent:sess_build_stalled"]
    assert orphan["started_by_instance"] is None and orphan["slot_id"] is None
    assert {"starter_unknown", "slot_unresolved"} <= {entry["kind"] for entry in orphan["unknowns"]}
