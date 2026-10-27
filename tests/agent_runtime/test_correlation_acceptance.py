"""CI-3: the scripted cross-process acceptance for one gesture's correlation token.

The serve line is written by the REAL producer (``office_read.log_office_write``) through a
formatter with hermes' ``asctime`` spelling; the two launcher receipts are hand-spelled from the
launcher's ``MissionTransportReceipt.toWireJson`` (another repository: nothing here can call it).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from agent_runtime.correlation_acceptance import (
    VERDICT_JOINED,
    VERDICT_MISSING,
    VERDICT_OUT_OF_ORDER,
    join_token,
)

TOKEN = "g-office-1a2b3c"
UTC0 = timedelta(0)


def _receipt(kind: str, at: datetime, corr: str, detail: str = "") -> str:
    return json.dumps({"v": 1, "at": at.isoformat().replace("+00:00", "Z"), "kind": kind,
                       "detail": detail, "corr": corr})


def _serve_line(at: datetime, corr: str | None) -> str:
    """One ``office_write`` line from the real producer, stamped at *at* (UTC, offset 0)."""

    from agent_runtime.serve_rpc import office_read

    lines: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            record.created = at.timestamp()
            record.msecs = (record.created % 1) * 1000
            lines.append(self.format(record))

    handler = _Capture()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    formatter.converter = lambda secs: datetime.fromtimestamp(secs, timezone.utc).timetuple()
    handler.setFormatter(formatter)
    logger = office_read.logger
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        office_read.log_office_write(op="runtime.office.remove", correlation_id=corr, workspace="ws_1")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    assert len(lines) == 1, lines
    return lines[0]


def _gesture(send_s: float, serve_s: float, fold_s: float, *, corr: str = TOKEN):
    t0 = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    receipts = [
        _receipt("office_write_sent", t0 + timedelta(seconds=send_s), TOKEN, "runtime.office.remove"),
        _receipt("fold_applied", t0 + timedelta(seconds=fold_s), f"g-other-9,{corr}", "entries:1"),
    ]
    serve = ["2026-10-27 11:59:59,000 INFO x: unrelated", _serve_line(t0 + timedelta(seconds=serve_s), TOKEN)]
    return [("receipts.jsonl", receipts), ("agent.log", serve)]


def test_one_gesture_joins_send_serve_fold_in_order():
    report = join_token(TOKEN, _gesture(0.0, 0.2, 0.6), serve_offset=UTC0)
    assert report["verdict"] == VERDICT_JOINED, report
    assert list(report["hops"]) == ["send", "serve", "fold"]
    assert report["hops"]["serve"]["detail"] == "runtime.office.remove"


def test_a_serve_receipt_after_the_fold_is_out_of_order():
    """*Kill:* drop the order check in ``join_token`` (any three hops read ``joined``) -> this reds."""

    report = join_token(TOKEN, _gesture(0.0, 0.9, 0.6), serve_offset=UTC0)
    assert report["verdict"] == VERDICT_OUT_OF_ORDER, report


def test_a_missing_hop_is_missing_never_a_pass():
    sources = _gesture(0.0, 0.2, 0.6, corr="g-someone-else")
    report = join_token(TOKEN, sources, serve_offset=UTC0)
    assert report["verdict"] == VERDICT_MISSING and report["missing"] == ["fold"], report


def test_the_serve_offset_moves_local_stamps_onto_utc():
    """The serve log is LOCAL time: read a +60 min box's line with offset 0 and it lands an hour late."""

    sources = _gesture(0.0, 3600.2, 0.6)
    assert join_token(TOKEN, sources, serve_offset=UTC0)["verdict"] == VERDICT_OUT_OF_ORDER
    assert join_token(TOKEN, sources, serve_offset=timedelta(minutes=60))["verdict"] == VERDICT_JOINED


def test_the_script_exits_by_verdict(tmp_path, capsys):
    from scripts.correlation_id_acceptance import EXIT_JOINED, EXIT_MISSING, EXIT_OUT_OF_ORDER, main

    def run(sources) -> int:
        (tmp_path / "r.jsonl").write_text("\n".join(sources[0][1]) + "\n", encoding="utf-8")
        (tmp_path / "a.log").write_text("\n".join(sources[1][1]) + "\n", encoding="utf-8")
        return main(["--token", TOKEN, "--receipts", str(tmp_path / "r.jsonl"),
                     "--serve-log", str(tmp_path / "a.log"), "--serve-utc-offset-minutes", "0"])

    assert run(_gesture(0.0, 0.2, 0.6)) == EXIT_JOINED
    assert run(_gesture(0.0, 0.9, 0.6)) == EXIT_OUT_OF_ORDER
    assert run(_gesture(0.0, 0.2, 0.6, corr="g-x")) == EXIT_MISSING
    assert main(["--token", TOKEN, "--receipts", str(tmp_path / "gone"), "--serve-log", str(tmp_path / "a.log")]) == EXIT_MISSING
    capsys.readouterr()
