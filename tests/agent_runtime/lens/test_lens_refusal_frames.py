"""Every Lens refusal reaches Eternia in ONE frame, whichever part of Lens refused.

Row ``RT-LENS-RPC-REFUSALS-FIVE-EXCEPTION-SHAPES``. Five modules refuse (the wire floor, the
seal's account check, the store, the recipe shelf, the artifact reader); each raises a
``lens.wire_value.LensRefusal`` and ``serve_rpc.lens._lens_call`` has one clause for it. The frame
is ``{code, message, data: {reason, detail}}``: the code is the refusal's kind, ``detail`` is
``""`` when nothing is named.

Before this row the three sources that named no field (owner, store, artifact) sent no
``data.detail`` at all while the wire floor and the shelf sent ``""``; every code, message and
reason below is the one each source already sent.

Each guarantee names the mutation that kills it; the reds are in the commit that landed this file.

* one frame from each source, through the verbs — killed by ``_lens_call`` sending ``detail`` only
  when it is not empty, and by ``LensStoreError.refused_as = RefusalKind.INVALID``;
* a refusal class needs no clause of its own — killed by ``LensArtifactError`` deriving from
  ``ValueError`` again (the walk loses the family and the verb answers a handler failure);
* every kind has a code — killed by dropping ``"conflict"`` from ``_REFUSAL_CODES``;
* the recipe family's document-class refusals are typed too — killed by dropping
  ``RecipeRefusal.UNREADABLE_DOCUMENT``.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import agent_runtime.lens
from agent_runtime import paths
from agent_runtime.lens.recipe_shelf import LENS_RECIPE_FAMILY, RecipeRefusal
from agent_runtime.lens.wire_value import LensRefusal, RefusalKind
from agent_runtime.realm_sync import document_family
from agent_runtime.serve_rpc.lens import _REFUSAL_CODES, _lens_call
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, ERR_NOT_FOUND

WORKSPACE = "ws_team"
EPISODE = "a" * 64
WIRE, OWNER, STORE, ARTIFACT = ("The Lens request was refused.", "Invalid conversation owner.",
                                "The Lens store refused the request.", "The Lens artifact was refused.")

#: source, verb, params -> code, message, reason, detail. ``draft-only`` is a never-sealed monitor
#: and ``m`` a sealed one with a command source (:func:`_refusing_home`).
FRAMES = [
    ("wire", "runtime.lens.get", {}, ERR_INVALID_PARAMS, WIRE, "invalid_string", ""),
    ("wire", "runtime.lens.recipe.add", {"recipe_id": "x", "monitor_id": "x"},
     ERR_INVALID_PARAMS, WIRE, "unknown_key", "monitor_id"),
    ("owner", "runtime.lens.seal", {"monitor_id": "draft-only", "client_scope": 5},
     ERR_INVALID_PARAMS, OWNER, "invalid_client_scope", ""),
    ("store", "runtime.lens.get", {"monitor_id": "absent"}, ERR_NOT_FOUND, STORE, "monitor_not_found", ""),
    ("store", "runtime.lens.draft.drop", {"monitor_id": "draft-only"}, ERR_CONFLICT, STORE, "not_sealed", ""),
    ("recipe", "runtime.lens.recipe.withdraw", {"workspace_id": WORKSPACE, "recipe_id": "absent"},
     ERR_NOT_FOUND, "This workspace shares no recipe of that id.", "recipe_not_found", ""),
    ("recipe", "runtime.lens.recipe.share", {"monitor_id": "m"}, ERR_CONFLICT,
     "A recipe may only carry http_json, prometheus and push sources.", "recipe_not_portable", "f"),
    ("artifact", "runtime.lens.artifact", {"episode_id": EPISODE, "name": "x.txt"},
     ERR_NOT_FOUND, ARTIFACT, "artifact_not_found", ""),
    ("artifact", "runtime.lens.artifact", {"episode_id": EPISODE, "name": "../x.txt"},
     ERR_INVALID_PARAMS, ARTIFACT, "outside_episode_folder", ""),
]


def _rpc(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def _refusing_home() -> None:
    def manifest(monitor_id: str, kind: str, source: dict) -> dict:
        feed = {"version": 1, "id": "f", "kind": kind, "interval_ms": 5000, "source": source}
        return {"version": 1, "monitor_id": monitor_id, "feeds": [feed], "rules": [], "persona_id": None,
                "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0}}

    http = manifest("draft-only", "http_json", {"url": "https://status.example.invalid/health", "selector": "$.cpu"})
    command = manifest("m", "command_allowlisted", {"argv": ["uptime"], "allow": [["uptime"]], "extract": "$.load"})
    for made in (http, command):
        assert "result" in _rpc("runtime.lens.create", {"manifest": made, "workspace_id": WORKSPACE})
    assert "result" in _rpc("runtime.lens.seal", {"monitor_id": "m"})


@pytest.mark.parametrize(("source", "verb", "params", "code", "message", "reason", "detail"), FRAMES,
                         ids=[f"{row[0]}:{row[5]}" for row in FRAMES])
def test_a_refusal_from_each_source_is_the_one_frame(source, verb, params, code, message, reason, detail):
    _refusing_home()
    assert _rpc(verb, params)["error"] == {"code": code, "message": message,
                                           "data": {"reason": reason, "detail": detail}}


def _families() -> list[type[LensRefusal]]:
    """Every refusal class Lens defines, read off the package itself."""

    for module in pkgutil.walk_packages(agent_runtime.lens.__path__, "agent_runtime.lens."):
        importlib.import_module(module.name)
    found, queue = [], list(LensRefusal.__subclasses__())
    while queue:
        family = queue.pop()
        found.append(family)
        queue.extend(family.__subclasses__())
    return found


def test_every_refusal_class_answers_through_the_one_clause_with_its_kind_s_code():
    families = _families()
    assert {family.__name__ for family in families} >= {
        "WireError", "LensOwnerError", "LensStoreError", "RecipeDocumentError", "LensArtifactError"}
    assert set(_REFUSAL_CODES) == {kind.value for kind in RefusalKind}
    codes = {RefusalKind.INVALID: ERR_INVALID_PARAMS, RefusalKind.NOT_FOUND: ERR_NOT_FOUND,
             RefusalKind.CONFLICT: ERR_CONFLICT}
    for family in families:
        assert family.not_found_reasons <= set(family.reasons), family
        for reason in family.reasons:
            def refuse(family=family, reason=reason):
                raise family(reason)

            error = _lens_call(1, refuse)["error"]
            kind = RefusalKind.NOT_FOUND if reason in family.not_found_reasons else family.refused_as
            assert (error["code"], error["data"]) == (codes[kind], {"reason": reason.value, "detail": ""}), reason
            assert error["message"], reason
        with pytest.raises(ValueError):
            family("not_a_reason_of_this_family")


def test_a_document_class_refusal_of_a_recipe_is_typed_and_framed():
    codes = {value for name, value in vars(document_family).items() if name.startswith("REFUSAL_")}
    assert codes and codes | {LENS_RECIPE_FAMILY.unreadable_reason} <= {member.value for member in RecipeRefusal}
    broken = paths.lens_recipe_path(WORKSPACE, "broken")
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"not json at all")
    assert _rpc("runtime.lens.recipe.add", {"workspace_id": WORKSPACE, "recipe_id": "broken"})["error"] == {
        "code": ERR_CONFLICT, "message": "unreadable_document",
        "data": {"reason": "unreadable_document", "detail": ""}}
