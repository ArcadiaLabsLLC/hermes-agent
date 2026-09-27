"""Disposable native-event translation. Native epoch/sequence owns replay."""
import json

from .projection import event_frames

__layer__ = "lanes"
_PAGE_BYTES = 600 * 1024


def read_page(live, native, cursor, offset):
    rows, size, consumed = [], 0, cursor
    receipts = {}
    for event in native["events"]:
        execution_id = event.get("execution_id", "")
        if execution_id not in receipts:
            receipts[execution_id] = live.store.execution(live.route, execution_id) if execution_id else None
        receipt = receipts[execution_id]
        for index, frame in enumerate(event_frames({"method": "event", "params": event})):
            if index < offset:
                continue
            row = {"seq": event["seq"], "turn_id": receipt.turn_id if receipt else None, "frame": frame}
            cost = len(json.dumps(row, ensure_ascii=True))
            if rows and size + cost > _PAGE_BYTES:
                return _page(native, rows, consumed, index, True)
            rows.append(row)
            size += cost
        consumed, offset = event["seq"], 0
    return _page(native, rows, max(consumed, native["latest_seq"]), 0, False)


def _page(native, rows, cursor, offset, more):
    return {"events": rows, "cursor": cursor, "offset": offset, "epoch": native["epoch"],
            "more": more, "truncated": False, "open_requests": native.get("open_requests", [])}
