"""``runtime.prefab.*`` -- a profile's user prefab shelf over the method lane.

Runtime-queue row (w5-rt, owner ruling 2026-09-30): the launcher's
``UserPrefabStore`` had only a SharedPreferences shelf; these four verbs are the
hermes store it binds. Pinned here: the shelf is per PROFILE (two profiles never
see each other's prefabs), the bytes are stored verbatim, ``list`` carries no
document, the label rule is the launcher's (case-folded, per shelf), and the
compare-and-set token is the stored bytes' sha256.
"""

from __future__ import annotations

import hashlib
import json

from agent_runtime import paths
from agent_runtime.prefab_store import PrefabStore
from tests.agent_runtime.test_serve_rpc_office import SHUTDOWN, _reply, _rpc, _run

PROFILE = "acct_one"

#: Not canonically serialised, so "stored verbatim" is falsifiable.
DOCUMENT = ('{\n  "v": 1,\n  "id": "up1",\n  "label": "Desk cluster",\n'
            '  "savedAt": "2026-10-02T10:00:00Z",\n  "document": {"version": 9, "scene": {"props": [1]}}\n}')


def _call(rid: str, method: str, params: dict) -> dict:
    return _reply(_run([_rpc(rid, method, params), SHUTDOWN]), rid)


def _doc(label: str) -> str:
    return json.dumps({"v": 1, "label": label, "document": {"version": 9}})


def test_set_get_list_clear_round_trip_verbatim_per_profile():
    reply = _call("p-1", "runtime.prefab.set", {"profile": PROFILE, "prefab_id": "up1", "document": DOCUMENT,
                                                "expect_sha256": None})
    sha = hashlib.sha256(DOCUMENT.encode("utf-8")).hexdigest()
    assert reply["result"]["changed"] is True and reply["result"]["sha256"] == sha
    assert paths.prefab_path(PROFILE, "up1").read_bytes() == DOCUMENT.encode("utf-8")

    listed = _call("p-2", "runtime.prefab.list", {"profile": PROFILE})["result"]
    assert listed["count"] == 1
    row = listed["prefabs"][0]
    assert (row["prefab_id"], row["label"], row["saved_at"], row["sha256"]) == (
        "up1", "Desk cluster", "2026-10-02T10:00:00Z", sha)
    assert "document" not in row

    got = _call("p-3", "runtime.prefab.get", {"profile": PROFILE, "prefab_id": "up1"})["result"]
    assert got["document"] == DOCUMENT

    other = _call("p-4", "runtime.prefab.list", {"profile": "acct_two"})["result"]
    assert other == {"profile": "acct_two", "prefabs": [], "count": 0}

    cleared = _call("p-5", "runtime.prefab.clear", {"profile": PROFILE, "prefab_id": "up1", "expect_sha256": sha})
    assert cleared["result"]["cleared"] is True
    again = _call("p-6", "runtime.prefab.clear", {"profile": PROFILE, "prefab_id": "up1"})
    assert again["result"]["cleared"] is False


def test_get_of_an_absent_prefab_is_not_found():
    reply = _call("p-7", "runtime.prefab.get", {"profile": PROFILE, "prefab_id": "nope"})
    assert reply["error"]["data"]["reason"] == "prefab_not_found"


def test_every_verb_requires_the_profile():
    for method in ("list", "get", "set", "clear"):
        reply = _call("p-8", f"runtime.prefab.{method}", {"prefab_id": "up1", "document": DOCUMENT})
        assert reply["error"]["data"]["reason"] == "profile_required", method


def test_a_document_without_a_label_or_fragment_is_refused_by_code():
    for body, reason in (
        ({"v": 1, "document": {}}, "label_invalid"),
        ({"v": 1, "label": "  ", "document": {}}, "label_invalid"),
        ({"v": 1, "label": "x"}, "fragment_missing"),
    ):
        reply = _call("p-9", "runtime.prefab.set", {"profile": PROFILE, "prefab_id": "up9",
                                                     "document": json.dumps(body)})
        assert reply["error"]["data"]["reason"] == reason
    assert not paths.prefab_path(PROFILE, "up9").exists()


def test_a_label_another_prefab_on_the_shelf_holds_is_taken_but_not_across_profiles():
    PrefabStore(PROFILE).write("upA", _doc("Arch").encode("utf-8"))
    taken = _call("p-10", "runtime.prefab.set", {"profile": PROFILE, "prefab_id": "upB", "document": _doc(" arch ")})
    assert taken["error"]["data"]["reason"] == "label_taken"
    assert taken["error"]["data"]["held_by"] == "upA"
    # Positive controls: its own label is not taken, and another profile's shelf is separate.
    resave = _call("p-11", "runtime.prefab.set", {"profile": PROFILE, "prefab_id": "upA", "document": _doc("Arch")})
    assert resave["result"]["changed"] is False
    elsewhere = _call("p-12", "runtime.prefab.set", {"profile": "acct_two", "prefab_id": "upB", "document": _doc("Arch")})
    assert elsewhere["result"]["changed"] is True


def test_a_stale_expectation_is_a_conflict_carrying_the_current_sha():
    PrefabStore(PROFILE).write("upC", _doc("Column").encode("utf-8"))
    current = hashlib.sha256(_doc("Column").encode("utf-8")).hexdigest()
    reply = _call("p-13", "runtime.prefab.set", {"profile": PROFILE, "prefab_id": "upC",
                                                  "document": _doc("Column 2"), "expect_sha256": "0" * 64})
    assert reply["error"]["data"]["reason"] == "sha256_mismatch"
    assert reply["error"]["data"]["current_sha256"] == current
    minted = _call("p-14", "runtime.prefab.set", {"profile": PROFILE, "prefab_id": "upC",
                                                   "document": _doc("Column 2"), "expect_sha256": None})
    assert minted["error"]["data"]["reason"] == "sha256_mismatch"
