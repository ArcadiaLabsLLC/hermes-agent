"""h-boot-pileup: a standalone ``harness stream`` rides the live serve's build.

On 2026-10-06 (agent.log 20:22–20:24:56, serve pid 40444) two argv children the
launcher spawned through a serve recycle each built a full core in their own
process (31 s and 51 s, ``caller=cli executor=in_process``) beside the serve's
own 70 s first build. These tests pin the cut: with a live serve on the store,
the CLI process calls ``stream_frames`` ZERO times and the frames it prints are
the serve's; with no serve it builds in-process exactly as before; inside the
serve it never dials itself. And a budget on the two sections that cost the
most at boot, ``agents_readiness`` and ``prompt_observability``, against a
seeded store.
"""

from __future__ import annotations

import argparse
import io
import json
import threading
import time

import pytest

from hermes_cli.harness_parts import runtime_commands, stream_relay
from hermes_cli.harness_parts.serve.argv_lane import dispatch_argv
from hermes_cli.harness_parts.serve.frames import current_serve_request_id
from tests.agent_runtime.test_serve_socket_lane import running_serve


def _stream_args(**overrides) -> argparse.Namespace:
    values = {
        "poll_interval": 0.25,
        "heartbeat_interval": 5.0,
        "delta_debounce_ms": 200,
        "max_frames": 1,
        "resync": False,
        "fold_entities": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class _FramesSpy:
    """Stands in for ``agent_runtime.stream.stream_frames``: one hydrate, and a
    record of WHO asked — the thread and the serve request bound to it."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(
            {
                "thread": threading.current_thread().name,
                "serve_request_id": current_serve_request_id(),
                "caller": kwargs.get("caller"),
                "max_frames": kwargs.get("max_frames"),
            }
        )
        yield {"type": "hydrate", "core": {"marker": "built-by-the-serve"}}


def test_a_cli_hydrate_while_a_serve_runs_builds_nothing_in_process(
    isolate_agent_runtime_root, monkeypatch
):
    spy = _FramesSpy()
    monkeypatch.setattr("agent_runtime.stream.stream_frames", spy)
    # The serve under test is a thread of THIS process, so its registry row
    # carries this pid; the self-dial guard would (correctly) refuse it.
    monkeypatch.setattr(stream_relay, "_this_pid", lambda: -1)

    out = io.StringIO()
    with running_serve(dispatch=dispatch_argv):
        code = stream_relay.relay_stream_via_serve(_stream_args(), out=out)

    assert code == 0
    # The positive half: the build happened, inside a serve request.
    assert len(spy.calls) == 1, spy.calls
    assert spy.calls[0]["serve_request_id"], spy.calls
    assert spy.calls[0]["caller"] == "cli"
    assert spy.calls[0]["max_frames"] == 1
    # The negative half: none of it on the asking thread.
    assert spy.calls[0]["thread"] != threading.current_thread().name
    frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert frames == [{"type": "hydrate", "core": {"marker": "built-by-the-serve"}}]


def test_with_no_live_serve_the_cli_builds_in_process(isolate_agent_runtime_root, monkeypatch):
    spy = _FramesSpy()
    monkeypatch.setattr("agent_runtime.stream.stream_frames", spy)

    assert stream_relay.relay_stream_via_serve(_stream_args(), out=io.StringIO()) is None
    assert runtime_commands._cmd_stream(_stream_args()) == 0
    assert len(spy.calls) == 1
    assert spy.calls[0]["serve_request_id"] is None
    assert spy.calls[0]["caller"] == "cli"


def test_the_cli_verb_asks_the_serve_before_it_builds(monkeypatch):
    spy = _FramesSpy()
    asked: list[object] = []
    monkeypatch.setattr("agent_runtime.stream.stream_frames", spy)
    monkeypatch.setattr(
        stream_relay, "relay_stream_via_serve", lambda args: asked.append(args) or 0
    )

    assert runtime_commands._cmd_stream(_stream_args()) == 0
    assert len(asked) == 1
    assert spy.calls == []


def test_inside_a_serve_request_the_verb_never_dials(monkeypatch):
    from hermes_cli.harness_parts.serve import frames as serve_frames

    spy = _FramesSpy()
    monkeypatch.setattr("agent_runtime.stream.stream_frames", spy)

    def _refuse(args):
        raise AssertionError("the serve's own stream request dialled the serve")

    monkeypatch.setattr(stream_relay, "relay_stream_via_serve", _refuse)
    token = serve_frames._request_id.set("req-inside-serve")
    try:
        assert runtime_commands._cmd_stream(_stream_args()) == 0
    finally:
        serve_frames._request_id.reset(token)
    assert len(spy.calls) == 1


def test_the_relayed_argv_round_trips_through_the_real_parser():
    from hermes_cli.harness import build_parser

    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers(dest="command"))
    for overrides in (
        {},
        {"max_frames": None, "resync": True, "fold_entities": ""},
        {"fold_entities": "persona_instance,incident", "delta_debounce_ms": 0},
    ):
        args = _stream_args(**overrides)
        parsed = parser.parse_args(stream_relay.stream_relay_argv(args))
        for key, value in vars(args).items():
            assert getattr(parsed, key) == value, (key, overrides)


# ── the budget: the two sections that cost 35 s / 30 s cold at boot ─────────

#: Measured 2026-10-06 against a copy of the operator's store, one process: a
#: warm build pays agents_readiness 0.4–1.3 s and prompt_observability 1.0–1.9 s
#: for 11 personas and ~2,000 SKILL.md files. The seeded store below is a
#: fraction of that, so a section over this budget on its SECOND build has lost
#: a per-process cache rather than grown with the data.
_WARM_SECTION_BUDGET_MS = 1500
_SEEDED_SKILLS = 60
_SEEDED_PERSONAS = 4


@pytest.fixture
def seeded_store(isolate_agent_runtime_root):
    import os
    from pathlib import Path

    from agent_runtime.models import AgentPersona
    from agent_runtime.store import AgentStore

    home = Path(os.environ["HERMES_HOME"])
    names = []
    for index in range(_SEEDED_SKILLS):
        name = f"seeded-skill-{index:03d}"
        skill_dir = home / "skills" / f"category-{index % 6}" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Seeded skill {index}.\n"
            "metadata:\n  hermes:\n    tags: [seeded, budget]\n---\n\n# Body\n",
            encoding="utf-8",
        )
        names.append(name)
    for index in range(_SEEDED_PERSONAS):
        AgentStore().save(
            AgentPersona(
                id=f"budget_persona_{index}",
                display_name=f"Budget Persona {index}",
                role="qa",
                model=None,
                provider=None,
                api_mode=None,
                system_prompt_path="",
                skills=names[index * 10 : index * 10 + 10],
            )
        )
    return names


@pytest.mark.timeout(120)
def test_the_boot_sections_stay_inside_their_warm_budget(seeded_store):
    from agent_runtime.snapshot import build_snapshot

    def _sections() -> dict:
        snapshot = build_snapshot()
        return dict((snapshot.get("parity") or {}).get("sections_ms") or {})

    started = time.monotonic()
    first = _sections()
    assert time.monotonic() - started < 60
    # Anti-vacuity: both sections ran over the seeded roster.
    assert "agents_readiness" in first and "prompt_observability" in first
    warm = _sections()
    for section in ("agents_readiness", "prompt_observability"):
        assert warm[section] <= _WARM_SECTION_BUDGET_MS, (section, warm[section], first[section])
