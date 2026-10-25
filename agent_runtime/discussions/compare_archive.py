"""Bounded, immutable Launcher Compare archives on the hosted-room journal.

Archive events are historical data, never messages, tasks or delivery receipts.
The imported bytes retain removed members, reset threads and uncertain replies.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re

from gateway import hosted_rooms as rooms
from .definitions import DefinitionError, ParticipantRef, fields, identifier, revision
from .run_values import DiscussionError

__layer__ = "stores"

CHUNK_BYTES = 128 * 1024
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
ARCHIVE_KIND = "history.compare_chunk"


def compare_source(value):
    value = fields(value, {"id", "revision", "name", "sha256", "bytes", "members"}, field="source")
    result = {"id": identifier(value["id"], "source_id"),
              "revision": revision(value["revision"]), "name": value["name"],
              "sha256": value["sha256"], "bytes": value["bytes"]}
    if (not isinstance(result["name"], str) or not 1 <= len(result["name"]) <= 160
            or not isinstance(result["sha256"], str) or re.fullmatch(r"[a-f0-9]{64}", result["sha256"]) is None
            or type(result["bytes"]) is not int or not 1 <= result["bytes"] <= MAX_ARCHIVE_BYTES):
        raise DefinitionError("invalid_compare_archive", "source")
    members = value["members"]
    if not isinstance(members, list) or not 1 <= len(members) <= 8:
        raise DefinitionError("invalid_compare_members", "members")
    result["members"] = []
    for row in members:
        row = fields(row, {"member_id", "participant", "profile", "session_id"}, field="members")
        result["members"].append({"member_id": identifier(row["member_id"], "member_id"),
            "participant": ParticipantRef.parse(row["participant"]).to_dict(),
            "profile": identifier(row["profile"], "profile"),
            "session_id": identifier(row["session_id"], "session_id") if row["session_id"] is not None else None})
    if (len({m["member_id"] for m in result["members"]}) != len(members)
            or len({(m["participant"]["install_id"], m["participant"]["instance_id"])
                    for m in result["members"]}) != len(members)):
        raise DefinitionError("duplicate_compare_member", "members")
    return result


def chunk_count(source):
    return (source["bytes"] + CHUNK_BYTES - 1) // CHUNK_BYTES


def decode_chunk(data):
    if not isinstance(data, str) or len(data) > 4 * ((CHUNK_BYTES + 2) // 3):
        raise DiscussionError("invalid_archive_chunk")
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DiscussionError("invalid_archive_chunk") from exc
    if not raw or base64.b64encode(raw).decode("ascii") != data:
        raise DiscussionError("invalid_archive_chunk")
    return raw


def append_chunk(service, run, index, data):
    source = run["initial"]["compare_import"]["source"]
    if type(index) is not int or not 0 <= index < chunk_count(source):
        raise DiscussionError("invalid_archive_chunk")
    raw = decode_chunk(data)
    expected = min(CHUNK_BYTES, source["bytes"] - index * CHUNK_BYTES)
    if len(raw) != expected:
        raise DiscussionError("invalid_archive_chunk")
    return rooms.append_event(service.db_path, room_id=run["run_id"], event_id=f"compare-archive:{index}",
        kind=ARCHIVE_KIND, actor={"kind": "gateway", "id": service.context.install_id},
        payload={"index": index, "data": data}, authority_gateway_id=service.context.install_id, authority_epoch=1)


def read_archive(service, run):
    source = run["initial"]["compare_import"]["source"]
    chunks, cursor = {}, 0
    while True:
        page = rooms.read_events(service.db_path, room_id=run["run_id"], since_seq=cursor, limit=3)
        for event in page["events"]:
            if event["kind"] == ARCHIVE_KIND:
                chunks[event["payload"]["index"]] = decode_chunk(event["payload"]["data"])
        cursor = page["cursor"]
        if not page["has_more"]:
            break
    if set(chunks) != set(range(chunk_count(source))):
        raise DiscussionError("archive_incomplete")
    raw = b"".join(chunks[index] for index in range(len(chunks)))
    if len(raw) != source["bytes"] or hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise DiscussionError("archive_digest_mismatch")
    _verify_record(raw, source)
    return raw


def _verify_record(raw, source):
    try:
        archive = json.loads(raw)
        if archive["version"] != 1 or len(archive["rooms"]) != 1:
            raise ValueError("one versioned room required")
        record = archive["rooms"][0]
        definition = record["definition"]
        actual = [(m["id"]) for m in definition["members"]]
        expected = [m["member_id"] for m in source["members"]]
        sessions = {s["member"]: json.loads(s["thread"])["threads"][0]["session"] for s in record["sessions"]}
        if (definition["id"] != source["id"] or definition["title"] != source["name"]
                or record["revision"] != source["revision"] or actual != expected
                or set(sessions) - set(expected)
                or any(sessions.get(m["member_id"]) != m["session_id"] for m in source["members"])):
            raise ValueError("source changed")
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError) as exc:
        raise DiscussionError("archive_source_mismatch") from exc
