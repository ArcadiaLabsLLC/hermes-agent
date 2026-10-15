"""A batch may overlap only distinct members answering the same public message."""
import json
from collections.abc import Mapping, Sequence


def independent_members(candidate: Mapping, active: Sequence[Mapping]) -> bool:
    payload = json.loads(candidate["payload_json"])
    member = payload.get("target_member_id")
    source = payload.get("source_event_seq")
    if payload.get("independent") is not True or not member or type(source) is not int or source < 1:
        return False
    for row in active:
        other = json.loads(row["payload_json"])
        if (other.get("independent") is not True
                or not other.get("target_member_id") or other["target_member_id"] == member
                or other.get("source_event_seq") != source
                or row["thread_id"] != candidate["thread_id"]):
            return False
    return True
