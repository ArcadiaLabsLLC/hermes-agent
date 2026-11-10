"""Task-scoped dispatch threads on the agent-to-agent relay (agent_chat_send → mission-chat).

Split out of ``test_relay_session_lifecycle.py`` (FH-PREPUSH-TOUCHED-RELAY-LIFECYCLE-OVER-BUDGET): that
file alone took 64 s of the prepush touched step's 60 s budget, so its V3 half — the dispatch
handler lane, fresh-per-dispatch threads, lineage, replays and the clarify round trip — lives here
and runs in its own process beside the session-lifecycle half. The chokepoint guarantees they share
are stated in that file's docstring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    persona_instance_id_for,
    resolve_default_chat_session_id_for_instance,
)
from agent_runtime.persona_chat_history import (
    PERSONA_CHAT_SESSION_SOURCE,
    persona_chat_history_summary,
)
from hermes_cli.harness_parts.persona import (
    chat_delete,
    chat_open,
    chat_request,
    chat_tickets_commands,
    chat_turn_message,
    inspect_commands,
    instance_commands,
    lifecycle_commands,
    model_and_skills_commands,
)
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run, settle as commit_settle
# The same autouse persona seed the lifecycle half runs under.
from tests.agent_runtime.test_relay_session_lifecycle import _persist_explicit_chat_persona_data  # noqa: F401


# --------------------------------------------------------------------------- #
# Task-scoped dispatch sessions (2026-07-27)                                  #
#                                                                             #
# The 2026-07-18 fix above made an omitted-session relay CONTINUE the target's #
# default thread. Correct for a conversation, wrong for a dispatch: a mission  #
# lead briefing one teammate on ten unrelated tasks piled all ten into one     #
# thread that was re-fed to the provider every turn (observed: 293K input      #
# tokens for a 1.7K-output task). A dispatch now opens its OWN thread by       #
# default, records the thread it superseded, and reports how the thread was    #
# established — while the 2026-07-18 guarantees hold: the mint still rides the #
# canonical chokepoint, so the session is pointed, canonical, and visible.     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def dispatch_home(tmp_path, monkeypatch):
    """A throwaway home for the handler lane.

    Driving the real handler reaches ``active_profile_name()``, which reads
    ``Path.home()/.hermes/active_profile``. The hermetic runner blanks the home
    env vars, so ``Path.home()`` raises there — and pointing at the developer's
    REAL home would make the test read live profile state. Give it a temp one."""

    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True, exist_ok=True)
    for var in ("HOME", "USERPROFILE", "HERMES_HOME"):
        monkeypatch.setenv(var, str(home))
    return home


class _DispatchTranscriptDB:
    """Minimal SessionDB stand-in for driving the handler end to end."""

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.messages: dict[str, list] = {}
        self.titles: dict[str, str] = {}

    def create_session(self, session_id, source, **kwargs):
        self.sessions.setdefault(session_id, {"source": source, **kwargs})
        self.messages.setdefault(session_id, [])
        return session_id

    def get_session_model_config_value(self, session_id, key, default=None):
        return self.session_meta(session_id).get(key, default)

    def get_session(self, session_id):
        session = self.sessions.get(session_id)
        if session is None:
            return None
        return {
            "id": session_id,
            "source": session.get("source"),
            "system_prompt": session.get("system_prompt"),
            "model": session.get("model"),
            "model_config": session.get("model_config"),
            "title": self.titles.get(session_id),
            "preview": None,
            "message_count": len(self.messages.get(session_id, [])),
            "started_at": None,
            "last_active": None,
            "archived": 0,
        }

    def list_sessions_rich(self, **kwargs):
        source = kwargs.get("source")
        exclude_sources = set(kwargs.get("exclude_sources") or [])
        rows = []
        for session_id, session in self.sessions.items():
            row_source = session.get("source")
            if source and row_source != source:
                continue
            if row_source in exclude_sources:
                continue
            rows.append({**self.get_session(session_id)})
        return rows

    def append_message(self, session_id, role, content=None, **kwargs):
        self.messages.setdefault(session_id, []).append({"role": role, "content": content, **kwargs})
        return len(self.messages[session_id])

    def get_messages(self, session_id, include_inactive=False):
        return list(self.messages.get(session_id, []))

    def get_session_title(self, session_id):
        return self.titles.get(session_id)

    def set_session_title(self, session_id, title):
        self.titles[session_id] = title

    def update_session_meta(self, session_id, model_config_json, model=None):
        session = self.sessions.setdefault(session_id, {})
        session["model_config"] = model_config_json
        if model is not None:
            session["model"] = model

    def delete_session(self, session_id, **kwargs):
        return bool(self.sessions.pop(session_id, None))

    def session_meta(self, session_id) -> dict:
        import json as _json

        raw = (self.sessions.get(session_id) or {}).get("model_config")
        return _json.loads(raw) if raw else {}


def _dispatch_args(message: str, client_message_id: str, **overrides):
    """Args as agent_chat_send builds them: no session, no new_session opinion."""

    from types import SimpleNamespace

    base = dict(
        persona_id="dev",
        persona_instance_id=None,
        session_id=None,
        task_id=None,
        goal_id=None,
        title=None,
        message=message,
        provider=None,
        model=None,
        use_agent_default=False,
        surface_prompt="",
        intent_hint="chat",
        requested_by="agent:worker_session_lead",
        requested_by_session=None,
        client_message_id=client_message_id,
        stream=False,
        max_seconds=5.0,
        json=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _install_dispatch_handler_doubles(monkeypatch, *, clarify_request=None):
    """Stub the model turn + transcript store; keep the REAL session lane."""

    from agent_runtime.config import AgentRuntimeConfig

    db = _DispatchTranscriptDB()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: AgentRuntimeConfig())
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: AgentRuntimeConfig())
    monkeypatch.setattr(inspect_commands, "load_agent_runtime_config", lambda: AgentRuntimeConfig())
    monkeypatch.setattr(instance_commands, "load_agent_runtime_config", lambda: AgentRuntimeConfig())
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: AgentRuntimeConfig())
    monkeypatch.setattr(model_and_skills_commands, "load_agent_runtime_config", lambda: AgentRuntimeConfig())
    monkeypatch.setattr(chat_delete, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr("agent_runtime.chat_verbs.turn_resolve._default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(commit_settle, "_maybe_auto_title_persona_chat", lambda **_kwargs: None)

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona_arg, message, **kwargs):
            from types import SimpleNamespace

            raw = {
                "model_input_observability": {
                    "kind": "redaction_safe_final_model_input",
                    "message_count": 1,
                    "messages": [],
                }
            }
            if clarify_request is not None:
                raw["clarify_request"] = clarify_request
            return SimpleNamespace(
                final_response="ack",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                raw=raw,
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)
    return db


def _send(capsys, args) -> dict:
    import json as _json

    code = chat_turn_message._cmd_mission_chat_message(args)
    payload = _json.loads(capsys.readouterr().out)
    assert code == 0, payload
    assert payload["ok"] is True
    return payload


def _refused(capsys, args) -> dict:
    """Drive the same handler for a send it must REFUSE."""

    import json as _json

    code = chat_turn_message._cmd_mission_chat_message(args)
    payload = _json.loads(capsys.readouterr().out)
    assert code == 2, payload
    assert payload["ok"] is False
    return payload


def _dev_chat_sessions(db) -> list[str]:
    prefix = f"persona_chat_{persona_instance_id_for('dev')}_"
    return [session_id for session_id in db.sessions if session_id.startswith(prefix)]


def test_dispatch_default_opens_a_fresh_thread_per_task(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    _install_dispatch_handler_doubles(monkeypatch)

    first = _send(capsys, _dispatch_args("triage the flaky login test", "cm-dispatch-1"))
    second = _send(capsys, _dispatch_args("audit the download resume path", "cm-dispatch-2"))

    assert first["session_id"] != second["session_id"], (
        "two unrelated dispatches must not share one mega-thread"
    )
    for payload in (first, second):
        assert payload["session_established"]["fresh"] is True
        assert payload["session_established"]["reason"] == "policy_new_per_dispatch"


def test_fresh_dispatch_thread_is_canonical_pointed_and_visible(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # The 2026-07-18 orphaned-relay guarantee must survive the new default: the
    # mint rides the canonical chokepoint, so the session belongs to the
    # canonical instance, becomes its pointer, and renders in the projection.
    db = _install_dispatch_handler_doubles(monkeypatch)

    payload = _send(capsys, _dispatch_args("investigate the cold-start cost", "cm-dispatch-3"))
    session_id = payload["session_id"]
    handle = persona_instance_id_for("dev")

    assert session_id.startswith(f"persona_chat_{handle}_")
    store = PersonaInstanceStore()
    assert resolve_default_chat_session_id_for_instance(store, persona_id="dev") == session_id
    rows = persona_chat_history_summary(persona_instances=store.list_all(), session_db=db)
    visible = [row for row in rows if row["session_id"] == session_id]
    assert len(visible) == 1
    assert visible[0]["persona_instance_id"] == handle


def test_fresh_dispatch_records_the_thread_it_superseded(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # Lineage, not amnesia: the retired thread is reachable from the new one via
    # the session meta, and named in the reply envelope.
    db = _install_dispatch_handler_doubles(monkeypatch)

    first = _send(capsys, _dispatch_args("task one", "cm-lineage-1"))
    second = _send(
        capsys,
        _dispatch_args("task two", "cm-lineage-2", requested_by_session="worker_session_lead"),
    )

    assert second["session_established"]["predecessor_session_id"] == first["session_id"]
    lineage = db.session_meta(second["session_id"])["_dispatched_from"]
    assert lineage["predecessor_chat_session_id"] == first["session_id"]
    assert lineage["requested_by_session"] == "worker_session_lead"
    # The very first dispatch had nothing to supersede — honest null, not a
    # self-reference.
    assert first["session_established"]["predecessor_session_id"] is None
    assert "_dispatched_from" not in db.session_meta(first["session_id"])


def test_dispatch_lineage_never_borrows_parent_session_id(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # parent_session_id is claimed by native-compression lineage on this lane
    # (native_lineage_summary raises on a foreign parent; usage aggregation
    # blanks). Relay provenance must ride its own marker key.
    db = _install_dispatch_handler_doubles(monkeypatch)

    _send(capsys, _dispatch_args("task one", "cm-parent-1"))
    second = _send(capsys, _dispatch_args("task two", "cm-parent-2"))

    meta = db.session_meta(second["session_id"])
    assert "_dispatched_from" in meta
    assert "parent_session_id" not in meta


def test_explicit_continuation_keeps_the_durable_pair_thread(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # new_session=False is a real answer, not "unset": it continues the durable
    # thread even while the policy default is new_per_dispatch. This is also the
    # CLI/serve operator-console lane (argparse store_true gives explicit False).
    _install_dispatch_handler_doubles(monkeypatch)

    first = _send(capsys, _dispatch_args("hello", "cm-sticky-1", new_session=False))
    second = _send(capsys, _dispatch_args("still here", "cm-sticky-2", new_session=False))

    assert second["session_id"] == first["session_id"]
    # Asserted key BY KEY, not as an exact dict: the exact-dict form pinned the
    # ABSENCE of every other envelope field as contract, so additive work
    # elsewhere broke a test that has nothing to say about it. All three values
    # this test actually cares about are still pinned, exactly as before.
    established = second["session_established"]
    assert established["fresh"] is False
    assert established["reason"] == "sticky_default"
    assert established["predecessor_session_id"] is None
    # The first send had no thread to continue, so it minted one — reported
    # honestly as fresh, with the sticky reason it was actually decided by.
    assert first["session_established"]["fresh"] is True
    assert first["session_established"]["reason"] == "sticky_default"


def test_sticky_continuation_follows_the_latest_thread_not_a_pair_thread(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # The retired vocabulary said new_session=false continues "the durable pair
    # thread". There is no such thread: every fresh dispatch repoints the
    # instance's default-thread pointer through open_chat, so "continue" means
    # the MOST RECENTLY established thread. Interleave the two lanes and pin the
    # actual pointer semantics — a conversation you want to keep is continued by
    # its session_id, never by a flag.
    _install_dispatch_handler_doubles(monkeypatch)

    conversation = _send(
        capsys, _dispatch_args("how are the builds looking", "cm-interleave-1", new_session=False)
    )
    dispatched = _send(capsys, _dispatch_args("audit the download resume path", "cm-interleave-2"))
    followed = _send(
        capsys, _dispatch_args("and the flaky login test?", "cm-interleave-3", new_session=False)
    )

    assert dispatched["session_id"] != conversation["session_id"], (
        "the dispatch must open its own task thread"
    )
    # THE point: the sticky send lands in the DISPATCH-minted thread, because
    # that is what the pointer now names — not back in the earlier conversation.
    assert followed["session_id"] == dispatched["session_id"]
    # Key by key, not an exact dict — same reason as the sibling sticky case
    # above: the shape of the whole envelope is not what this test is about, and
    # pinning it here only made additive work fail in the wrong place.
    established = followed["session_established"]
    assert established["fresh"] is False
    assert established["reason"] == "sticky_default"
    assert established["predecessor_session_id"] is None
    # The earlier conversation is not lost, just no longer the default: it is
    # continued by naming it, which is exactly what the contract now says.
    resumed = _send(
        capsys,
        _dispatch_args("back to the builds", "cm-interleave-4", session_id=conversation["session_id"]),
    )
    assert resumed["session_id"] == conversation["session_id"]
    assert resumed["session_established"]["reason"] == "explicit_session_id"


def test_a_dispatch_refused_on_its_own_arguments_mints_nothing(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # Minting before validating meant every retried or refused dispatch left a
    # titled empty thread in the sidebar. Under new_per_dispatch that is not a
    # cosmetic leak: the mint also repoints the default-thread pointer, so a
    # refusal would steal the thread the next sticky send continues.
    db = _install_dispatch_handler_doubles(monkeypatch)

    blank = _refused(capsys, _dispatch_args("   ", "cm-reject-message"))
    assert blank["error"] == "message is required"

    override = _refused(
        capsys,
        _dispatch_args(
            "triage the flaky login test",
            "cm-reject-override",
            use_agent_default=True,
            model="gpt-5-codex",
        ),
    )
    assert override["error_kind"] == "invalid_chat_model_override"

    assert _dev_chat_sessions(db) == [], "a refused dispatch must not create a thread"
    assert (
        resolve_default_chat_session_id_for_instance(PersonaInstanceStore(), persona_id="dev")
        is None
    ), "a refused dispatch must not establish a default-thread pointer"


def test_a_refused_dispatch_leaves_an_established_thread_pointed_where_it_was(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # The repoint half of the same bug: with a live thread already in place, a
    # refused dispatch must not mint a successor and repoint onto it.
    db = _install_dispatch_handler_doubles(monkeypatch)

    established = _send(capsys, _dispatch_args("task one", "cm-keep-pointer-1"))
    _refused(
        capsys,
        _dispatch_args(
            "task two",
            "cm-keep-pointer-2",
            use_agent_default=True,
            provider="not a provider",
        ),
    )

    assert _dev_chat_sessions(db) == [established["session_id"]]
    assert resolve_default_chat_session_id_for_instance(
        PersonaInstanceStore(), persona_id="dev"
    ) == established["session_id"]


def test_a_replayed_dispatch_reports_the_same_thread_lineage(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # A resend of the same client_message_id is the SAME turn answered again:
    # the mint receipt is idempotency-keyed, so it lands back in the thread it
    # established. The envelope must say so — a caller that reads
    # session_established to decide where its follow-up goes cannot have that
    # answer vanish on a retry.
    db = _install_dispatch_handler_doubles(monkeypatch)

    earlier = _send(capsys, _dispatch_args("task one", "cm-replay-1"))
    second = _send(capsys, _dispatch_args("triage the flaky login test", "cm-replay-2"))
    replay = _send(capsys, _dispatch_args("triage the flaky login test", "cm-replay-2"))

    assert replay["idempotent_replay"] is True
    assert replay["session_id"] == second["session_id"]
    assert replay["session_established"] == second["session_established"]
    assert replay["session_established"]["predecessor_session_id"] == earlier["session_id"]
    # …and the retry did not rewrite the session's own lineage into a loop: by
    # the time it ran, the default-thread pointer WAS this thread.
    lineage = db.session_meta(second["session_id"])["_dispatched_from"]
    assert lineage["predecessor_chat_session_id"] == earlier["session_id"]


def test_a_replayed_relay_dispatch_keeps_the_provenance_it_was_born_with(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # THE relay lane, not a hypothetical: agent_chat_send always forwards
    # requested_by_session, so a replay's recomputed lineage is never empty —
    # the self-referential predecessor drops out and the sender key keeps the
    # dict truthy. Re-deriving would then write {requested_by_session} over the
    # stored block (this meta write replaces it wholesale) and ERASE the real
    # predecessor. Lineage is established once, by the mint that created the
    # thread; a retry carries it, it does not recompute it.
    db = _install_dispatch_handler_doubles(monkeypatch)

    earlier = _send(
        capsys,
        _dispatch_args("task one", "cm-relay-replay-1", requested_by_session="worker_lead"),
    )
    dispatched = _send(
        capsys,
        _dispatch_args(
            "triage the flaky login test",
            "cm-relay-replay-2",
            requested_by_session="worker_lead",
        ),
    )
    # The retry arrives from a DIFFERENT sender session: who asked for the thread
    # is a fact about the mint that opened it, not about whoever resent the turn.
    replay = _send(
        capsys,
        _dispatch_args(
            "triage the flaky login test",
            "cm-relay-replay-2",
            requested_by_session="worker_second",
        ),
    )

    assert replay["session_id"] == dispatched["session_id"]
    assert replay["session_established"] == dispatched["session_established"]
    assert replay["session_established"]["predecessor_session_id"] == earlier["session_id"]
    lineage = db.session_meta(dispatched["session_id"])["_dispatched_from"]
    assert lineage["predecessor_chat_session_id"] == earlier["session_id"]
    assert lineage["requested_by_session"] == "worker_lead"


def test_an_interleaved_retry_never_claims_the_thread_that_followed_it(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # Replay of dispatch A AFTER dispatch B ran. The pointer now names B, so A's
    # re-read "predecessor" is not even a self-reference any more — it survives
    # the drop rule and would record "A superseded B". Backwards fabrication: A
    # came first and superseded nothing. The arrow a lineage reader follows must
    # never be invented by the order retries happen to arrive in.
    db = _install_dispatch_handler_doubles(monkeypatch)

    first = _send(capsys, _dispatch_args("task one", "cm-interleaved-1"))
    second = _send(capsys, _dispatch_args("task two", "cm-interleaved-2"))
    assert second["session_established"]["predecessor_session_id"] == first["session_id"]

    replay = _send(capsys, _dispatch_args("task one", "cm-interleaved-1"))

    assert replay["session_id"] == first["session_id"]
    assert replay["session_established"]["predecessor_session_id"] is None
    assert "_dispatched_from" not in db.session_meta(first["session_id"])
    # …and B's lineage is untouched by A's retry: it still names A.
    assert db.session_meta(second["session_id"])["_dispatched_from"] == {
        "predecessor_chat_session_id": first["session_id"]
    }


def test_sticky_policy_restores_the_durable_thread_for_unset_callers(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    import agent_runtime.config.knobs as runtime_config_module

    monkeypatch.setattr(
        runtime_config_module, "mission_chat_dispatch_session_policy", lambda cfg=None: "sticky"
    )
    _install_dispatch_handler_doubles(monkeypatch)

    first = _send(capsys, _dispatch_args("task one", "cm-policy-sticky-1"))
    second = _send(capsys, _dispatch_args("task two", "cm-policy-sticky-2"))

    assert second["session_id"] == first["session_id"]
    assert second["session_established"]["reason"] == "policy_sticky"
    assert second["session_established"]["fresh"] is False


def test_explicit_session_id_continues_that_exact_thread(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    _install_dispatch_handler_doubles(monkeypatch)

    opened = _send(capsys, _dispatch_args("start the task", "cm-explicit-1"))
    followed = _send(
        capsys,
        _dispatch_args("one more detail", "cm-explicit-2", session_id=opened["session_id"]),
    )

    assert followed["session_id"] == opened["session_id"]
    # Asserted key BY KEY, not as an exact dict. The exact-dict form pinned the
    # ABSENCE of every other field as contract, so any additive envelope work
    # broke a test that has nothing to say about it (the clarify-binding block
    # is a top-level sibling for exactly this reason). What this test is about
    # is the three values below.
    established = followed["session_established"]
    assert established["fresh"] is False
    assert established["reason"] == "explicit_session_id"
    assert established["predecessor_session_id"] is None


def test_clarify_round_trip_stays_in_one_session_under_the_new_default(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # THE correctness check for the flipped default. A briefed agent that asks a
    # clarifying question must be answerable IN THAT THREAD — the answer carries
    # the session_id the reply returned. If the answer relied on stickiness it
    # would now open a third thread and the agent would read the choice with no
    # question attached.
    db = _install_dispatch_handler_doubles(
        monkeypatch,
        clarify_request={"question": "launcher or backend?", "choices": ["launcher", "backend"]},
    )

    dispatched = _send(capsys, _dispatch_args("fix the failing test", "cm-clarify-1"))
    assert dispatched["clarify_request"] is not None
    assert dispatched["session_established"]["fresh"] is True

    answer = _send(
        capsys,
        _dispatch_args("launcher", "cm-clarify-2", session_id=dispatched["session_id"]),
    )

    assert answer["session_id"] == dispatched["session_id"]
    assert answer["session_established"]["reason"] == "explicit_session_id"
    # One thread for the whole exchange — the question and its answer are in it.
    chat_sessions = [
        session_id
        for session_id in db.sessions
        if session_id.startswith(f"persona_chat_{persona_instance_id_for('dev')}_")
    ]
    assert chat_sessions == [dispatched["session_id"]]
    # …and the answer did not mint a second one behind the caller's back.
    assert answer["session_established"]["fresh"] is False
    assert answer["session_established"]["predecessor_session_id"] is None
    assert resolve_default_chat_session_id_for_instance(
        PersonaInstanceStore(), persona_id="dev"
    ) == dispatched["session_id"]


class _StrictDispatchTranscriptDB(_DispatchTranscriptDB):
    """The same double, but seen as real persistence by the handler's guards.

    ``unknown_chat_session`` / ``foreign_chat_session`` may only refuse against a
    store where "no row" MEANS "no such session", so they ask
    ``is_canonical_session_persistence``. The clarify design's load-bearing claim
    is that a token gets BOTH guards for free by resolving before them, and
    proving that requires a double those guards actually look at.

    It declares itself under its OWN name. This class used to spoof
    ``__module__ = "hermes_state"`` — a double claiming to be a module it is not,
    purely in order to be believed — which is what forced the predicate to exist:
    a guard reachable only by a lying test asset is not honestly tested."""

    __hermes_canonical_session_persistence__ = True


def _mint_clarify_ticket(session_id: str, **overrides) -> str:
    from agent_runtime.persona_chat_continuity import PersonaChatClarifyTicketStore

    token = PersonaChatClarifyTicketStore().mint(
        chat_session_id=session_id,
        persona_instance_id=persona_instance_id_for("dev"),
        persona_id="dev",
        asked_by_client_message_id="agent-relay-aaaaaaaaaaaa",
        **overrides,
    )
    assert token
    return token


def test_clarify_token_binds_the_answer_when_the_parent_names_no_session(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    """THE headline case, and the reason the token exists.

    Under ``new_per_dispatch`` an answer that names no session opens a THIRD
    thread and the child reads a bare choice with no question attached. The
    only thing that used to prevent it was prompt text asking a model to
    reproduce an opaque session id. Now the runtime owns the binding: the
    answer carries only the token and still lands in the question's thread."""

    db = _install_dispatch_handler_doubles(
        monkeypatch,
        clarify_request={"question": "launcher or backend?", "choices": ["launcher", "backend"]},
    )

    dispatched = _send(capsys, _dispatch_args("fix the failing test", "cm-token-1"))
    token = dispatched["clarify_request"]["clarify_token"]
    assert token.startswith("clarify-")

    answer = _send(
        capsys,
        _dispatch_args("launcher", "cm-token-2", clarify_token=token),
    )

    assert answer["session_id"] == dispatched["session_id"]
    assert answer["session_established"]["reason"] == "clarify_token"
    assert answer["session_established"]["fresh"] is False
    assert answer["clarify_binding"]["bound_via"] == "clarify_token"
    assert answer["clarify_binding"]["bound_session_id"] == dispatched["session_id"]
    assert answer["clarify_binding"]["overrode_session_id"] is None
    # One thread for the whole exchange — no third thread behind the caller's back.
    assert _dev_chat_sessions(db) == [dispatched["session_id"]]


def test_clarify_token_overrides_a_wrong_session_id_and_says_so(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # A caller unreliable enough to need the token is exactly the caller who
    # will also attach a stale session id. Refusing that would defeat the
    # design; landing it silently would hide a real disagreement. It lands, and
    # the override is named.
    _install_dispatch_handler_doubles(
        monkeypatch,
        clarify_request={"question": "launcher or backend?"},
    )

    stale = _send(capsys, _dispatch_args("earlier task", "cm-override-0"))
    asked = _send(capsys, _dispatch_args("fix the failing test", "cm-override-1"))
    token = asked["clarify_request"]["clarify_token"]
    assert stale["session_id"] != asked["session_id"]

    answer = _send(
        capsys,
        _dispatch_args(
            "launcher",
            "cm-override-2",
            clarify_token=token,
            session_id=stale["session_id"],
        ),
    )

    assert answer["session_id"] == asked["session_id"]
    assert answer["session_established"]["reason"] == "clarify_token"
    assert answer["clarify_binding"]["overrode_session_id"] == stale["session_id"]


def test_an_unknown_clarify_token_degrades_instead_of_refusing(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # Tickets are swept on a TTL, so a token CAN legitimately outlive its
    # record. Turning that into a hard failure would punish the parent that did
    # exactly the right thing — so the turn falls through to normal precedence
    # and reports why.
    _install_dispatch_handler_doubles(monkeypatch)

    answer = _send(
        capsys,
        _dispatch_args("launcher", "cm-unknown-1", clarify_token="clarify-deadbeefdead"),
    )

    assert answer["clarify_binding"]["state"] == "unknown_token"
    assert answer["clarify_binding"]["bound_via"] == "none"
    assert answer["session_established"]["reason"] == "policy_new_per_dispatch"


def test_a_clarify_token_cannot_smuggle_in_a_foreign_session(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    """Placement, not a new guard: resolution happens BEFORE the existing
    ownership checks, so a token naming another instance's thread is refused by
    the same ``foreign_chat_session`` every explicit session id already hits."""

    import json as _json

    db = _StrictDispatchTranscriptDB()
    _install_dispatch_handler_doubles(monkeypatch)
    monkeypatch.setattr(chat_delete, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr("agent_runtime.chat_verbs.turn_resolve._default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)

    foreign = f"persona_chat_{persona_instance_id_for('qa')}_abcdef123456"
    db.create_session(foreign, "agent_runtime_persona_chat")
    db.update_session_meta(
        foreign,
        _json.dumps(
            {
                "mission_chat_root_id": foreign,
                "persona_instance_id": persona_instance_id_for("qa"),
                "source": "agent_runtime_persona_chat",
            }
        ),
    )
    token = _mint_clarify_ticket(foreign)

    refusal = _refused(
        capsys, _dispatch_args("launcher", "cm-foreign-1", clarify_token=token)
    )

    assert refusal["error_kind"] == "foreign_chat_session"
    assert refusal["session_id"] == foreign


def test_a_prompt_compliant_answer_still_settles_the_open_question(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # A parent that answered correctly WITHOUT the token must not leave the
    # ticket open forever: the adoption metric would then read pessimistically
    # for every caller doing the right thing, which is the reading that would
    # argue for building more machinery than this needs.
    from agent_runtime.persona_chat_continuity import PersonaChatClarifyTicketStore

    _install_dispatch_handler_doubles(
        monkeypatch,
        clarify_request={"question": "launcher or backend?"},
    )

    asked = _send(capsys, _dispatch_args("fix the failing test", "cm-settle-1"))
    token = asked["clarify_request"]["clarify_token"]

    answer = _send(
        capsys,
        _dispatch_args("launcher", "cm-settle-2", session_id=asked["session_id"]),
    )

    assert answer["session_established"]["reason"] == "explicit_session_id"
    assert answer["clarify_binding"]["bound_via"] == "session_id"
    assert PersonaChatClarifyTicketStore().resolve(token)["state"] == "answered"


def test_the_clarify_gate_off_restores_the_pre_token_lane(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # The whole rollback: no token minted, none resolved, and the wire shape
    # reverts to {question, choices}. Nothing to migrate, nothing to unwind.

    monkeypatch.setattr(
        chat_request, "mission_chat_clarify_token_binding", lambda cfg=None: False
    )
    monkeypatch.setattr(
        chat_tickets_commands, "mission_chat_clarify_token_binding", lambda cfg=None: False
    )
    _install_dispatch_handler_doubles(
        monkeypatch,
        clarify_request={"question": "launcher or backend?"},
    )

    asked = _send(capsys, _dispatch_args("fix the failing test", "cm-gate-1"))
    assert asked["clarify_request"] == {"question": "launcher or backend?"}
    assert "clarify_binding" not in asked


def test_fresh_dispatch_threads_are_named_after_the_task(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # Task-scoped threads are only navigable when named; a sidebar of identical
    # "Dev chat" rows is worse than the mega-thread it replaced.
    db = _install_dispatch_handler_doubles(monkeypatch)

    derived = _send(
        capsys, _dispatch_args("Triage the flaky login test on Windows", "cm-title-1")
    )
    explicit = _send(
        capsys,
        _dispatch_args("anything", "cm-title-2", title="Download resume audit"),
    )

    assert db.get_session_title(derived["session_id"]) == "Triage the flaky login test on Windows"
    assert db.get_session_title(explicit["session_id"]) == "Download resume audit"


def test_the_durable_thread_keeps_its_persona_title(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # The operator console mints its first thread through this same lane and
    # passes a generic --title; that lane must keep the stable per-persona name
    # rather than being renamed after one message.
    db = _install_dispatch_handler_doubles(monkeypatch)

    opened = _send(
        capsys,
        _dispatch_args("hello there", "cm-console-1", new_session=False, title="Operator message"),
    )

    title = db.get_session_title(opened["session_id"])
    assert title.endswith(" chat"), title  # "<display name> chat", the durable name
    assert title not in ("Operator message", "hello there")


# ── dispatching at a retired placement ──────────────────────────────────────


def _retire_a_placement(placement_id: str = "dev_agent_2") -> tuple[str, str]:
    """A retired ``dev`` placement: the id, and its archive path."""

    store = PersonaInstanceStore()
    placement = store.add_instance(
        persona_id="dev", placement_id=placement_id, display_name="Dev (2)"
    )
    archived = store.retire(placement.id, reason="placement deleted")
    return placement.id, archived["archive_path"]


def _mint_receipt_files() -> list[Path]:
    from agent_runtime import paths

    receipts = paths.store_root() / "persona_chat_mint_receipts"
    return sorted(receipts.glob("*.json")) if receipts.exists() else []


def test_a_dispatch_to_a_retired_placement_mints_nothing(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # A retired placement is an end-of-life tombstone: `open_chat` refuses to
    # bind it. But the mint reaches `open_chat` LAST — after reserving the
    # receipt, creating the session row and titling it — so every dispatch at a
    # corpse left a titled thread in Mission Control, and the refusal arrived
    # from outside this call site's typed handler, i.e. as a traceback.
    db = _install_dispatch_handler_doubles(monkeypatch)
    retired_id, archive_path = _retire_a_placement()

    refusal = _refused(
        capsys,
        _dispatch_args(
            "triage the flaky login test",
            "cm-retired-1",
            persona_instance_id=retired_id,
        ),
    )

    assert refusal["error_kind"] == "retired_persona_instance"
    assert refusal["execution_state"] == "refused"
    assert refusal["persona_instance_id"] == retired_id
    assert refusal["archive_path"] == archive_path
    assert refusal["history_preserved"] is True
    # (a) no session row, (b) no mint receipt, (c) no default-thread pointer.
    assert db.sessions == {}, "a dispatch at a retired placement must not create a thread"
    assert _mint_receipt_files() == []
    store = PersonaInstanceStore()
    assert (
        resolve_default_chat_session_id_for_instance(
            store, persona_id="dev", persona_instance_id=retired_id
        )
        is None
    )
    # …and the refusal never revived the tombstoned row into the live roster.
    assert retired_id not in {row.id for row in store.list_all()}


def test_a_dispatch_whose_transcript_write_fails_refuses_instead_of_binding_a_phantom(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    """The mint's OTHER failure, seen from where an operator sees it.

    The mint binds the chat pointer BEFORE it writes the transcript row — the
    ordering that keeps a mid-lane ``retire`` from leaving a titled thread. Its
    cost is a window: a ``create_session`` that fails used to leave the
    instance pointing at a root no SessionDB holds, which never heals
    (``resolve_default_chat_session_id_for_instance`` re-offers a chat-shaped
    own-instance pointer without asking whether it resolves), so every later
    send to that agent was refused ``unknown_chat_session`` forever. And the
    storage exception itself escaped this call site's typed handler as a
    traceback.

    Now the bind is retracted and the turn refuses in the vocabulary the chat
    lanes already speak."""

    db = _install_dispatch_handler_doubles(monkeypatch)

    def _refuse_to_persist(self, *args, **kwargs):
        raise RuntimeError("transcript store went away")

    monkeypatch.setattr(type(db), "create_session", _refuse_to_persist)

    refusal = _refused(
        capsys, _dispatch_args("triage the flaky login test", "cm-persist-fail")
    )

    assert refusal["error_kind"] == "chat_session_persist_failed"
    assert refusal["persistence_operation"] == "session_create"
    # Nothing session-visible landed…
    assert db.sessions == {}
    # …and no phantom pointer survives to poison every later send.
    assert (
        resolve_default_chat_session_id_for_instance(
            PersonaInstanceStore(), persona_id="dev"
        )
        is None
    )
    # The RESERVATION does survive, on purpose: it is what makes a retry
    # resolve the same root instead of minting a second thread.
    assert len(_mint_receipt_files()) == 1


def test_a_dispatch_to_a_retired_placement_leaves_live_threads_alone(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # The repoint half: a live sibling's established thread must survive a
    # refused dispatch at the corpse untouched — pointer and all.
    db = _install_dispatch_handler_doubles(monkeypatch)
    retired_id, _ = _retire_a_placement()

    established = _send(capsys, _dispatch_args("task one", "cm-retired-live-1"))
    receipts_before = _mint_receipt_files()

    _refused(
        capsys,
        _dispatch_args("task two", "cm-retired-live-2", persona_instance_id=retired_id),
    )

    assert _dev_chat_sessions(db) == [established["session_id"]]
    assert list(db.sessions) == [established["session_id"]]
    assert _mint_receipt_files() == receipts_before
    assert resolve_default_chat_session_id_for_instance(
        PersonaInstanceStore(), persona_id="dev"
    ) == established["session_id"]


def test_a_streamed_dispatch_to_a_retired_placement_refuses_the_same_way(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    # The serve/stream lane must not be the one that still tracebacks: the
    # refusal is one `chat.final` frame carrying the same typed payload.
    import json as _json

    db = _install_dispatch_handler_doubles(monkeypatch)
    retired_id, archive_path = _retire_a_placement()

    code = chat_turn_message._cmd_mission_chat_message(
        _dispatch_args(
            "triage the flaky login test",
            "cm-retired-stream",
            persona_instance_id=retired_id,
            stream=True,
            json=False,
        )
    )

    frames = [
        _json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert code == 2
    assert [frame["type"] for frame in frames] == ["chat.final"]
    final = frames[0]
    assert final["ok"] is False
    assert final["error_kind"] == "retired_persona_instance"
    assert final["persona_instance_id"] == retired_id
    assert final["archive_path"] == archive_path
    assert db.sessions == {}
    assert _mint_receipt_files() == []


def test_a_retired_target_is_refused_before_the_mint_lane_is_ever_entered(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    """Pins the PRE-FLIGHT specifically, not just its outcome.

    Three enforcement points render one refusal body, so the tests above pass
    on any ONE of them: delete the pre-flight and the mint's own precondition
    answers byte-identically, green suite, no signal. But they are not
    interchangeable — the pre-flight is what keeps the lane from being ENTERED,
    and everything downstream of entering it (the receipt reserve, the session
    row, the retire race that opens once the mint is running) only stays
    impossible while the refusal lands first. So make the reach itself the
    failure: this ``mint`` cannot be called without failing the test.
    """

    from agent_runtime.persona_chat_continuity.mint_receipts import Mint

    db = _install_dispatch_handler_doubles(monkeypatch)
    retired_id, archive_path = _retire_a_placement()

    def _never_reached(self, *args, **kwargs):
        raise AssertionError(
            "the dispatch lane entered the mint for a retired target — the "
            "pre-mint refusal is no longer doing the work"
        )

    monkeypatch.setattr(Mint, "run", _never_reached)

    refusal = _refused(
        capsys,
        _dispatch_args(
            "triage the flaky login test",
            "cm-retired-preflight",
            persona_instance_id=retired_id,
        ),
    )

    # Same contract as the reachable-mint path: the operator cannot tell which
    # enforcement point fired, only that it fired before anything was written.
    assert refusal["error_kind"] == "retired_persona_instance"
    assert refusal["execution_state"] == "refused"
    assert refusal["persona_instance_id"] == retired_id
    assert refusal["archive_path"] == archive_path
    assert refusal["history_preserved"] is True
    assert db.sessions == {}
    assert _mint_receipt_files() == []


# --------------------------------------------------------------------------- #
# The removed operator route: task-bound instance chat roots (2026-07-29)     #
#                                                                             #
# Persona instances carry a lifecycle. The chat-mode on-level instances       #
# (`personainst_<role>_agent_<hash>`) are the operator's chat targets; the    #
# bare task-bound rows (`personainst_qa`, `personainst_goal_*`, …) belong to  #
# the goal graph and its daemon. Messaging a task-bound row's chat root       #
# WORKED mechanically — which is what made it worth removing, because the     #
# Mission Control console then misattributed the thread and the operator's    #
# chat rode a broken mission path with nothing to read. Operator ruling:      #
# remove the route, typed, with the redirect named.                           #
#                                                                             #
# The exemption is the whole design. The daemon/graph/worker lanes, root-node #
# engine turns and every agent-relay hop legitimately speak to these          #
# instances, so the guard fires ONLY on the bare operator send — no relay     #
# envelope, no --task/--goal.                                                 #
# --------------------------------------------------------------------------- #


def _task_bound_goal_instance(goal_id: str = "goal_alpha", persona_id: str = "dev"):
    """A representative historical task-bound row with a chat root."""

    from agent_runtime.models import AgentPersona

    persona = AgentPersona(
        id=persona_id,
        role="dev",
        display_name="Dev Agent",
        model="gpt-test",
        provider="openai-codex",
        api_mode="codex_responses",
        system_prompt_path="agent_runtime/prompts/dev.md",
        hermes_profile=None,
    )
    store = PersonaInstanceStore()
    instance = store.ensure_for_persona(persona)
    instance.mode = "task_bound"
    instance.goal_id = goal_id
    instance.current_task_id = goal_id
    instance = store.update(instance)
    # Stored task_bound; the decode reads the steer-shaped row as ordinary
    # (RT-TASK-BOUND-VOCABULARY), so the historical shape is checked on disk.
    import json as _json

    from agent_runtime import paths as _paths

    stored = _json.loads(_paths.persona_instance_path(instance.id).read_text(encoding="utf-8"))
    assert stored["mode"] == "task_bound", stored["mode"]
    return instance


def _seed_chat_root(db, instance) -> str:
    """Give *instance* a persona-chat root the handler's owner lookup resolves."""

    import json as _json

    root = f"persona_chat_{instance.id}_abcdef123456"
    db.create_session(root, PERSONA_CHAT_SESSION_SOURCE)
    db.update_session_meta(
        root,
        _json.dumps(
            {
                "mission_chat_root_id": root,
                "persona_instance_id": instance.id,
                "source": PERSONA_CHAT_SESSION_SOURCE,
            }
        ),
    )
    return root


def _install_strict_db(monkeypatch):
    """The dispatch doubles, but with a store the ownership guards may refuse on."""

    _install_dispatch_handler_doubles(monkeypatch)
    db = _StrictDispatchTranscriptDB()
    monkeypatch.setattr(chat_delete, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr("agent_runtime.chat_verbs.turn_resolve._default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)
    return db


def test_a_bare_operator_send_to_a_legacy_instance_root_is_accepted(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    """Legacy instance metadata no longer creates a separate mission lane."""

    db = _install_strict_db(monkeypatch)
    goal_instance = _task_bound_goal_instance()
    root = _seed_chat_root(db, goal_instance)
    # The redirect target: a real on-level placement, with its own bound root.
    on_level = PersonaInstanceStore().add_instance(
        persona_id="dev", placement_id="dev_agent_2", display_name="Dev (2)"
    )
    assert on_level.mode == "chat"

    payload = _send(
        capsys, _dispatch_args("status please", "cm-task-bound-1", session_id=root)
    )
    assert payload["session_id"] == root
    assert payload["persona_instance_id"] == goal_instance.id
    assert payload["reply"] == "ack"
    assert on_level.id != goal_instance.id


def test_legacy_root_guard_helpers_are_removed(
    isolate_agent_runtime_root,
):
    """No hidden compatibility helper can restore the removed route split."""

    from hermes_cli import harness

    names = ["_" + "task_bound" + "_chat_root_refusal", "_mission_chat_" + "carries_mission_context"]
    assert all(not hasattr(harness, name) for name in names)


def test_a_chat_mode_instance_root_is_still_accepted(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    """The route that REPLACES it. A guard that also broke this would be a
    regression dressed as a fix."""

    db = _install_strict_db(monkeypatch)
    on_level = PersonaInstanceStore().add_instance(
        persona_id="dev", placement_id="dev_agent_2", display_name="Dev (2)"
    )
    root = _seed_chat_root(db, on_level)

    payload = _send(
        capsys, _dispatch_args("status please", "cm-chat-mode-1", session_id=root)
    )

    assert payload["session_id"] == root
    assert payload["persona_instance_id"] == on_level.id


def test_a_relay_hop_reaches_a_legacy_instance_root(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    """EXEMPT LANE 1 — the agent-relay envelope.

    ``agent_chat_send`` always carries the running turn's chain, so a non-empty
    ``relay_chain`` is exactly "an agent is speaking, not the operator". The
    daemon/graph/worker lanes and root-node engine turns reach these instances
    through this same envelope, and removing the operator route must not touch
    any of them."""

    db = _install_strict_db(monkeypatch)
    goal_instance = _task_bound_goal_instance()
    root = _seed_chat_root(db, goal_instance)

    payload = _send(
        capsys,
        _dispatch_args(
            "stage 2 is ready for you",
            "cm-task-bound-relay",
            session_id=root,
            relay_chain=["neko_supervisor"],
        ),
    )

    assert payload["session_id"] == root
    assert payload["persona_instance_id"] == goal_instance.id
    # The turn actually RAN in the goal's own thread — the exemption is not just
    # "no refusal printed", it is a reply the relaying agent can read.
    assert payload["reply"] == "ack"


def test_an_explicit_legacy_goal_argument_does_not_change_chat_routing(
    monkeypatch, capsys, isolate_agent_runtime_root, dispatch_home
):
    """EXEMPT LANE 2 — mission context named on the turn itself.

    Not a proxy for the mission lane but the definition of it: the handler
    already treats ``--task``/``--goal`` as the authority that MAKES an instance
    task-bound, so a send carrying one is addressing the mission lane by
    construction."""

    db = _install_strict_db(monkeypatch)
    goal_instance = _task_bound_goal_instance()
    root = _seed_chat_root(db, goal_instance)

    payload = _send(
        capsys,
        _dispatch_args(
            "stage 2 is ready for you",
            "cm-task-bound-goal",
            session_id=root,
            goal_id="goal_alpha",
        ),
    )

    assert payload["session_id"] == root
    assert payload["persona_instance_id"] == goal_instance.id


def test_no_incoming_envelope_exemption_helper_remains(
    isolate_agent_runtime_root,
):
    """Chat routing no longer branches on mission-shaped envelope metadata."""
    from hermes_cli import harness

    assert not hasattr(harness, "_mission_chat_" + "carries_mission_context")
