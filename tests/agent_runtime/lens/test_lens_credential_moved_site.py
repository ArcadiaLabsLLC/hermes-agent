"""RT-LENS-UPDATE-MOVED-SITE-CANNOT-SIGN-IN-BEFORE-SEAL — a draft that moves a source to another
site is signed in before it is sealed, and the sealed revision keeps reading meanwhile.

The defect, reproduced through the verbs Eternia uses: a sealed monitor with a set sign-in, then a
next-revision draft naming the same credential at another site. ``runtime.lens.get`` listed the
sealed revision's sign-ins only, and ``runtime.lens.credential.set`` saw both sites and refused
``credential_host_ambiguous`` — so the moved source could only be signed in AFTER Seal, with the
monitor reading ``credential_host_mismatch`` in between.

Ruled 2026-11-15 (``lens/credentials.py`` module docstring): a name holds one sign-in per address,
and ``credential.set`` may say which of a monitor's two manifests the sign-in is for. Each
guarantee names the mutation that kills it; the reds are recorded in the commit that landed this file.

* the sealed revision keeps its own sign-in while the draft's is saved — killed by
  ``set_credential`` writing ``rows[ref] = [row]``;
* a secret is only ever sent to the address it was saved for — killed by ``_saved_for`` answering
  the first row whatever its ``host``;
* the request points at a manifest and the store reads the address off it — killed by
  ``credential.set`` ignoring ``monitor_id`` / ``revision`` (``chosen = live``);
* ``get`` says what Seal would run with — killed by ``draft_credentials`` reading the sealed manifest;
* a site no live manifest names any more loses its sign-in at the name's next save — killed by
  ``set_credential`` ignoring ``live_hosts``;
* the manifest a sign-in is for exists — killed by swapping the two rows of ``revision_manifest``.

No real network: every read goes through an ``httpx.MockTransport`` and a fixed resolver.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.lens.credentials import CredentialRefusal, credentials_path, resolve_credential
from tests.agent_runtime.lens.test_lens_credential_host import (
    ELSEWHERE, HOME_HOST, SECRET, _call, _feed, _manifest,
    wire,  # the fixture: every request the serve's HTTP client would send
)

ELSEWHERE_HOST = "https://collector.example.invalid:443"
NEW_SECRET = "Lm3-Qr8t-Vx2b-Np6s"
SET = {"ref": "k", "scheme": "bearer"}


def _ok(method: str, params: dict) -> dict:
    reply = _call(method, params)
    assert "result" in reply, reply
    return reply["result"]


def _reason(method: str, params: dict) -> str:
    return _call(method, params)["error"]["data"]["reason"]


def _sealed_then_moved() -> None:
    """``status`` sealed at HOME and signed in; its next-revision draft reads ELSEWHERE."""

    _ok("runtime.lens.create", {"manifest": _manifest("status")})
    _ok("runtime.lens.seal", {"monitor_id": "status"})
    _ok("runtime.lens.credential.set", {**SET, "secret": SECRET})
    _ok("runtime.lens.create", {"manifest": _manifest("status", _feed(ELSEWHERE))})


def _sign_ins(monitor_id: str = "status") -> tuple[list, list | None]:
    got = _ok("runtime.lens.get", {"monitor_id": monitor_id})
    rows = [None if rows is None else [(row["feed_id"], row["set"], row["host"]) for row in rows]
            for rows in (got["credentials"], got["draft_credentials"])]
    return rows[0], rows[1]


def test_a_moved_draft_is_signed_in_before_seal_and_the_sealed_revision_keeps_its_own(wire):
    _sealed_then_moved()
    # The reproduction: get said nothing of the draft, and set could not say which site it meant.
    assert _sign_ins() == ([("api", True, HOME_HOST)], [("api", False, HOME_HOST)])
    assert _reason("runtime.lens.credential.set", {**SET, "secret": NEW_SECRET}) == "credential_host_ambiguous"

    draft = {"monitor_id": "status", "revision": "draft"}
    saved = _ok("runtime.lens.credential.set", {**SET, "secret": NEW_SECRET, **draft})
    assert (saved["set"], saved["host"]) == (True, ELSEWHERE_HOST)  # the store's word, off the draft
    assert _sign_ins() == ([("api", True, HOME_HOST)], [("api", True, ELSEWHERE_HOST)])
    assert resolve_credential("k", host=HOME_HOST).secret == SECRET  # the running revision is untouched
    assert resolve_credential("k", host=ELSEWHERE_HOST).secret == NEW_SECRET

    # Each site gets its own secret and no other: one read of each manifest.
    for manifest in (_manifest("status"), _manifest("status", _feed(ELSEWHERE))):
        _ok("runtime.lens.preview", {"manifest": manifest})
    assert wire == [("status.example.invalid", f"Bearer {SECRET}"),
                    ("collector.example.invalid", f"Bearer {NEW_SECRET}")]

    # The sealed revision's own sign-in still rotates while the draft waits.
    rotated = _ok("runtime.lens.credential.set", {**SET, "secret": "rotated-home-value", "monitor_id": "status",
                                                  "revision": "sealed"})
    assert rotated["host"] == HOME_HOST
    assert resolve_credential("k", host=ELSEWHERE_HOST).secret == NEW_SECRET

    _ok("runtime.lens.seal", {"monitor_id": "status"})
    assert _sign_ins() == ([("api", True, ELSEWHERE_HOST)], None)  # sealed and reading at once


def test_a_site_no_live_manifest_names_loses_its_sign_in_at_the_next_save():
    _sealed_then_moved()
    _ok("runtime.lens.credential.set", {**SET, "secret": NEW_SECRET, "monitor_id": "status", "revision": "draft"})

    def held() -> list[str]:
        return [row["host"] for row in json.loads(credentials_path().read_text(encoding="utf-8"))["credentials"]["k"]]

    assert held() == [HOME_HOST, ELSEWHERE_HOST]
    _ok("runtime.lens.seal", {"monitor_id": "status"})  # nothing names HOME any more
    _ok("runtime.lens.credential.set", {**SET, "secret": NEW_SECRET})
    assert held() == [ELSEWHERE_HOST]
    assert resolve_credential("k", host=HOME_HOST) is CredentialRefusal.HOST_MISMATCH


@pytest.mark.parametrize(("params", "reason"), [
    ({"monitor_id": "nobody", "revision": "draft"}, "monitor_not_found"),
    ({"monitor_id": "sealed-only", "revision": "draft"}, "no_draft"),
    ({"monitor_id": "draft-only", "revision": "sealed"}, "not_sealed"),
    ({"monitor_id": "gone", "revision": "sealed"}, "monitor_retired"),
    ({"monitor_id": "sealed-only", "revision": "next"}, "unknown_enum"),
    ({"monitor_id": "sealed-only"}, "unknown_enum"),        # one without the other is not a pointer
    ({"revision": "sealed"}, "invalid_string"),
    ({"monitor_id": "other-ref", "revision": "draft"}, "credential_host_unknown"),  # it does not name ``k``
])
def test_a_sign_in_for_a_manifest_that_is_not_there_is_refused_and_saves_nothing(params, reason):
    for monitor_id in ("sealed-only", "gone"):
        _ok("runtime.lens.create", {"manifest": _manifest(monitor_id)})
        _ok("runtime.lens.seal", {"monitor_id": monitor_id})
    _ok("runtime.lens.retire", {"monitor_id": "gone"})
    _ok("runtime.lens.create", {"manifest": _manifest("draft-only")})
    _ok("runtime.lens.create", {"manifest": _manifest("other-ref", _feed(credential_ref="another"))})
    assert _reason("runtime.lens.credential.set", {**SET, "secret": SECRET, **params}) == reason
    assert resolve_credential("k", host=HOME_HOST) is CredentialRefusal.MISSING
