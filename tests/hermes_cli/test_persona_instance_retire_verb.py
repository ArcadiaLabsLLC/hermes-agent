"""``harness persona instance retire`` — the argv door onto ``perform_agent_retire``.

Every verb test drives the REAL argparse tree and dispatches through
``args.func``, never by poking the handler: a handler nothing routes to is a
verb no operator can run.

``harness agent retire`` was a second argv door onto the same service until
2026-10-02, when it was deleted (owner ruling: the launcher reaches it only as
``runtime.agent.retire``). Agents are placed here through the service itself,
``agent_create.perform_agent_create`` — the function ``runtime.agent.create``
answers with — because the argv ``agent create`` went in the same ruling.

Nothing here spawns a ``harness serve``: the claim is precisely that none is
needed.
"""

from __future__ import annotations

import argparse
import json

import pytest

from agent_runtime import paths
from tests.agent_runtime.office_seed import seed_workspace_record
from hermes_cli.harness_parts.persona import lifecycle_commands

WORKSPACE = "ws_persona_instance_retire_verb"


@pytest.fixture(autouse=True)
def hermetic_runtime_root(tmp_path, monkeypatch):
    """Pin the runtime root INSIDE this test's tmp dir, and prove it landed.

    These tests archive real rows, and a resolution regression would archive
    the OPERATOR's.
    """

    root = tmp_path / "agent-runtime"
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root))
    resolved = paths.store_root().resolve()
    assert resolved == root.resolve() or root.resolve() in resolved.parents, (
        f"store_root() resolved to {resolved}, OUTSIDE {root}: this test would "
        "write into a runtime root nobody in this repo controls."
    )
    return root


@pytest.fixture
def qa_persona():
    from agent_runtime.models import AgentPersona
    from agent_runtime.store import AgentStore

    persona = AgentPersona(
        id="qa",
        display_name="QA Agent",
        role="qa",
        model=None,
        provider=None,
        api_mode=None,
        toolsets=[],
        system_prompt_path="",
    )
    AgentStore().save(persona)
    return persona


@pytest.fixture
def seeded_workspace():
    from agent_runtime.office_store import OfficeStore

    seed_workspace_record(WORKSPACE)
    store = OfficeStore()
    store.ensure_surface(WORKSPACE, created_by="seed")
    return store


def _dispatch(argv: list[str]) -> int:
    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args(argv)
    return args.func(args)


def _place(capsys, placement_id: str = "qa_verb_retire_1_agent_2") -> dict:
    from agent_runtime.agent_create import perform_agent_create

    outcome = perform_agent_create(
        {
            "persona_id": "qa",
            "workspace_id": WORKSPACE,
            "position": [2, 2],
            "placement_id": placement_id,
            "idempotency_key": f"verb-retire-{placement_id}",
        }
    )
    assert outcome.refusal is None, outcome.refusal
    return outcome.result


def _retire(capsys, instance_id: str, *extra: str) -> tuple[int, dict]:
    """``(exit code, payload)``: the ack on success, the refusal envelope otherwise."""

    code = _dispatch(
        ["harness", "persona", "instance", "retire", instance_id, "--json", *extra]
    )
    data = json.loads(capsys.readouterr().out)
    return code, data.get("persona_instance_retired", data)


def _live_actor_keys() -> set:
    from agent_runtime.office_store import OfficeStore

    return {actor.actor_key for actor in OfficeStore().scan_actors(WORKSPACE).actors}


# ── the verb retires a placement ─────────────────────────────────────────────


def test_the_verb_archives_both_halves_and_names_the_actors(
    qa_persona, seeded_workspace, capsys
):
    """ANTI-VACUITY: the probe is the OFFICE store, not the ack.

    The kill-mutation is "route the verb at the roster archive alone" — which is
    what the launcher's two-lane removal degenerated to whenever its second lane
    failed. That mutant returns a perfectly plausible ack with the desk still on
    the canvas, so the desk is what gets read.
    """

    placed = _place(capsys)
    assert placed["actor_key"] in _live_actor_keys()

    code, data = _retire(capsys, placed["persona_instance_id"])

    assert code == 0
    assert data["archived_actor_keys"] == [placed["actor_key"]]
    assert data["office_archive_failures"] == []
    assert data["already_retired"] is False
    assert placed["actor_key"] not in _live_actor_keys()
    assert not paths.persona_instance_path(placed["persona_instance_id"]).exists()


def test_a_second_retire_is_answered_not_refused(qa_persona, seeded_workspace, capsys):
    """KILLING MUTATION: drop the tombstone probe in the service's ``not_found``
    arm — the verb refuses (exit 2) and this reds on ``code == 0``.

    An operator who runs the verb twice (or a cron that does) must not have to
    tell "already done" apart from "wrong id" by reading prose.
    """

    placed = _place(capsys, placement_id="qa_verb_retire_2_agent_2")
    _retire(capsys, placed["persona_instance_id"])

    code, data = _retire(capsys, placed["persona_instance_id"])

    assert code == 0
    assert data["already_retired"] is True
    assert data["archived_actor_keys"] == [placed["actor_key"]]


def test_a_guard_refusal_is_refused_with_its_reason(qa_persona, capsys):
    from agent_runtime.persona_assignments import PersonaInstanceStore

    canonical = PersonaInstanceStore().ensure_for_persona(qa_persona)

    code, data = _retire(capsys, canonical.id)

    assert code == 2
    assert data["code"] == "canonical_persona_channel"
    assert paths.persona_instance_path(canonical.id).exists()


# ── the two doors are one function ───────────────────────────────────────────


def test_the_argv_door_and_the_wire_door_answer_the_same_ack(
    qa_persona, seeded_workspace, capsys
):
    """KILLING MUTATION: point ``persona instance retire`` back at
    ``PersonaInstanceStore.retire`` directly — its payload loses
    ``archived_actor_keys`` / ``office_archive_failures`` / ``already_retired``
    and the key-set comparison reds.

    Two placements, because a retire is not repeatable against the same row; the
    comparison is of the ack's SHAPE and of every field that is not the row's
    own identity.
    """

    from agent_runtime import serve_rpc

    first = _place(capsys, placement_id="qa_verb_retire_3_agent_2")
    second = _place(capsys, placement_id="qa_verb_retire_4_agent_2")

    wire = serve_rpc.handle_request(
        {
            "jsonrpc": "2.0",
            "id": "r1",
            "method": "runtime.agent.retire",
            "params": {"persona_instance_id": first["persona_instance_id"]},
        }
    )["result"]

    code, ack = _retire(capsys, second["persona_instance_id"])
    assert code == 0

    assert set(ack) == set(wire)
    assert ack["archived_actor_keys"] == [second["actor_key"]]
    assert ack["office_archive_failures"] == []
    assert ack["already_retired"] is False
    assert ack["persona_id"] == wire["persona_id"] == "qa"


# ── the CLI's authorization identity (chokepoint plan A4) ────────────────────


def test_the_retire_door_carries_the_console_identity(
    qa_persona, seeded_workspace, capsys, monkeypatch
):
    """A4-iii. The console identity is minted in ``_agent_retire_outcome``, so
    refusing it must refuse the verb — BEFORE the service runs.

    Patched where the running handler looks the name up (lanes H1/H3: the
    handler's own module); a patch anywhere else would go green while the
    shipped path ran unpatched.
    """

    placed = _place(capsys, placement_id="qa_verb_retire_auth_1_agent_2")

    monkeypatch.setattr(
        lifecycle_commands,
        "_console_denial",
        lambda action: {
            "code": -32000,
            "message": f"{action} requires the console tier",
            "data": {"reason": "scope_denied", "tier": "console", "caller": "unknown"},
        },
    )

    code, data = _retire(capsys, placed["persona_instance_id"])

    assert code != 0
    assert data["ok"] is False
    assert data["code"] == "scope_denied"
    # ANTI-VACUITY: the refusal landed BEFORE the service, so the row survives.
    assert placed["actor_key"] in _live_actor_keys()


def test_a_plain_operator_retire_is_unchanged_by_the_mirror(
    qa_persona, seeded_workspace, capsys
):
    """The A3/A4 promise, on the verb: landing the gate must not change what an
    operator at their own shell observes.

    The console identity is a CONSTANT and reads nothing off the invocation, so
    a retire typed with the default ``--requested-by`` and one typed with any
    other spelling answer identically — which is also the proof that
    authorization no longer depends on the argv field the old coordinator gate
    keyed on.
    """

    plain = _place(capsys, placement_id="qa_verb_retire_plain_agent_2")
    spelled = _place(capsys, placement_id="qa_verb_retire_spelled_agent_2")

    plain_code, plain_ack = _retire(capsys, plain["persona_instance_id"])
    spelled_code, spelled_ack = _retire(
        capsys, spelled["persona_instance_id"], "--requested-by", "launcher"
    )

    assert plain_code == spelled_code == 0
    assert set(plain_ack) == set(spelled_ack)
    assert plain_ack["already_retired"] is spelled_ack["already_retired"] is False


def test_the_instance_door_refuses_with_the_services_typed_reason(
    qa_persona, seeded_workspace, capsys
):
    """The refusal is the SERVICE's, translated — not a second ``except`` over
    the same store guard. ``persona instance retire`` keeps its own historical
    spelling (``error``/``code`` carry the reason word, exit 2), and the reason
    word itself comes from the one place that maps the guard.
    """

    code = _dispatch(
        ["harness", "persona", "instance", "retire", "personainst_nope", "--json"]
    )
    data = json.loads(capsys.readouterr().out)

    assert code == 2
    assert data["ok"] is False
    assert data["error"] == "not_found"
    assert data["code"] == "not_found"


# ── the operator surface ─────────────────────────────────────────────────────


def test_the_human_readable_line_names_what_left_the_canvas(
    qa_persona, seeded_workspace, capsys
):
    """Without ``--json`` the verb still prints a line naming what it retired."""

    placed = _place(capsys, placement_id="qa_verb_retire_5_agent_2")

    code = _dispatch(
        ["harness", "persona", "instance", "retire", placed["persona_instance_id"]]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert out.startswith(f"retired {placed['persona_instance_id']} ")


# ── the gesture token reaches the store from argv (S8b) ─────────────────────


def test_a_retire_typed_without_the_flag_carries_no_token(
    qa_persona, seeded_workspace, capsys
):
    """The additive half, at the operator surface: the flag defaults to ``None``
    and an operator who does not type it gets the ack they always got.

    Also the fence for the ``getattr(..., None)`` default: an operator
    who omits the flag must reach the store with no token, not with a fabricated
    one. If that default were anything else, this arm would be the first thing
    to say so.
    """

    placed = _place(capsys, placement_id="qa_verb_retire_no_corr_agent_2")

    code, data = _retire(capsys, placed["persona_instance_id"])

    assert code == 0
    assert "correlation_id" not in data


def test_the_persona_instance_door_carries_the_token_too(
    qa_persona, seeded_workspace, capsys
):
    """S8b-b: the OTHER door onto ``perform_agent_retire`` publishes the flag.

    S8b withheld ``--correlation-id`` from ``harness persona instance retire`` on
    the stated grounds that "no gesture behind it is the truth for that door".
    That was false about its largest caller. The launcher's
    ``persona.instance.retire`` argv capability IS this door — fired from
    ``MissionOfficeLayoutController.retireAgent``'s ``Unavailable`` arm, whose
    ``correlationId`` parameter is REQUIRED — so a token existed on every
    launcher retire and was dropped by exactly the arm that runs when the RPC
    lane is degraded, which is when a grep over the event log is the only join
    an operator has.

    KILLING MUTATION (run, observed, reverted): delete the
    ``persona_instance_retire.add_argument("--correlation-id", ...)`` line in
    ``hermes_cli/harness.py``. Observed red::

        SystemExit: 2
        error: unrecognized arguments: --correlation-id g-office-...

    The EVENT is read as well as the ack, for the same anti-vacuity reason the
    sibling test gives: an ack that echoed the flag it was handed would satisfy
    an ack-only assertion with nothing on the wire to grep.
    """

    from agent_runtime.state_patches import CORRELATION_ID_KEY

    token = "g-office-1755400000999998-b2c3"
    placed = _place(capsys, placement_id="qa_verb_retire_corr_other_door_agent_2")

    code = _dispatch(
        [
            "harness", "persona", "instance", "retire",
            placed["persona_instance_id"],
            "--correlation-id", token,
            "--json",
        ]
    )
    data = json.loads(capsys.readouterr().out)

    assert code == 0, data
    assert data["persona_instance_retired"]["correlation_id"] == token

    from agent_runtime.events import EventLog

    removed = [
        event.payload
        for _, event in EventLog().iter_from_offset(0)
        if event.type == "office.actor.removed"
    ]
    assert [payload.get(CORRELATION_ID_KEY) for payload in removed] == [token]
    assert [payload.get("actor_key") for payload in removed] == [placed["actor_key"]]


# ── D4: the operator's verb is Delete ───────────────────────────────────────


def test_delete_is_the_same_parser_as_retire_and_cannot_drift_from_it():
    """D4. An argparse ALIAS, not a second parser.

    The operator ruling is about the WORD ("why retire it should just be
    delete"), so the two spellings must be one behaviour — and the way to
    guarantee that is structural rather than asserted verb by verb: one parser
    object means the flags, the defaults, the help and the handler are the same
    objects, so there is nothing left that COULD drift.

    Probed as the whole parsed namespace rather than just ``func``: a second
    parser wired to the same handler would satisfy a ``func`` check and still
    differ on a default nobody re-typed, which is precisely the failure a copied
    ``add_parser`` produces.
    """

    from hermes_cli import harness

    def _parse(spelling: str):
        root = argparse.ArgumentParser(prog="hermes")
        harness.build_parser(root.add_subparsers(dest="command"))
        return root.parse_args([
            "harness", "persona", "instance", spelling,
            "personainst_qa_agent_2",
            "--reason", "the operator dragged it off the level",
            "--requested-by", "cli",
            "--correlation-id", "g-delete-1",
            "--json",
        ])

    retire = vars(_parse("retire"))
    delete = vars(_parse("delete"))

    assert retire.pop("func").__name__ == "_cmd_persona_instance_retire"
    assert delete.pop("func").__name__ == "_cmd_persona_instance_retire"

    # The ONE field that legitimately differs: argparse records which spelling
    # the operator typed. Popped explicitly rather than ignored, so that if a
    # SECOND difference ever appears it reds here instead of hiding behind a
    # loosened comparison. Nothing reads this dest — checked: its only other
    # readers are the parser tests' own lookup tables — so recording the word
    # cannot become a behaviour.
    assert retire.pop("persona_instance_command") == "retire"
    assert delete.pop("persona_instance_command") == "delete"

    assert retire == delete


def test_the_delete_spelling_actually_retires_an_agent(
    qa_persona, seeded_workspace, capsys
):
    """ANTI-VACUITY for the alias above: a namespace comparison passes against a
    parser that routes nowhere. This one drives the verb end to end and reads
    the store."""

    from agent_runtime.office_store import OfficeStore

    placed = _place(capsys, placement_id="qa_verb_delete_agent_2")

    code = _dispatch([
        "harness", "persona", "instance", "delete",
        placed["persona_instance_id"],
        "--json",
    ])
    data = json.loads(capsys.readouterr().out)

    assert code == 0, data
    assert data["persona_instance_retired"]["persona_instance_id"] == (
        placed["persona_instance_id"]
    )
    # Both halves left, which is what makes Delete an honest word for it.
    assert OfficeStore().scan_actors(WORKSPACE).actors == []
