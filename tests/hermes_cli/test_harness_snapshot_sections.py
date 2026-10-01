"""``hermes harness snapshot --only`` (HQ4, 2026-10-01).

A caller that needs one slice of the frame asks for it instead of reading ~900 KB.
The guarantees, each pinned against a REAL frame built in a sandboxed runtime root
(the builder is then replayed from that one build, so every key the builder emits
is exercised and none is typed here):

* no ``--only`` → the full frame, byte for byte what the verb printed before;
* ``--only K`` → exactly ``{K: frame[K]}``, for every top-level key K;
* an unknown key → refused (exit 2, ``invalid_request``) with the frame's key list,
  and no frame printed — never a silently partial answer.
"""

from __future__ import annotations

import argparse
import json

import pytest

from agent_runtime.cli_format import emit_json
from hermes_cli.harness import build_parser


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers(dest="command"))
    return parser


@pytest.fixture
def built_frame(tmp_path, monkeypatch):
    """One real build, replayed as a fresh copy on every ``build_snapshot()`` call."""

    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    init = _parser().parse_args(["harness", "init", "--json"])
    assert init.func(init) == 0

    from agent_runtime.snapshot.build import build_snapshot

    frozen = emit_json(build_snapshot())
    monkeypatch.setattr("agent_runtime.snapshot.build.build_snapshot", lambda *a, **k: json.loads(frozen))
    frame = json.loads(frozen)
    frame.setdefault("parity", {})["frame_source"] = "built"  # what the verb stamps on every frame
    return frame


def _run(argv, capsys):
    capsys.readouterr()
    args = _parser().parse_args(["harness", "snapshot", *argv])
    rc = args.func(args)
    return rc, capsys.readouterr().out


def test_without_only_the_full_frame_prints_byte_for_byte(built_frame, capsys):
    rc, out = _run(["--json"], capsys)

    assert rc == 0
    assert out == emit_json(built_frame) + "\n"
    # The frame is a real multi-section one, so "full" is a claim with teeth.
    assert len(built_frame) > 10
    assert set(json.loads(out)) == set(built_frame)


def test_each_section_alone_prints_exactly_that_section(built_frame, capsys):
    for section in built_frame:
        rc, out = _run(["--only", section, "--json"], capsys)
        assert rc == 0, section
        assert json.loads(out) == {section: built_frame[section]}, section


def test_several_sections_print_together_whatever_the_order_asked(built_frame, capsys):
    rc, out = _run(["--only", "boards, agents,boards", "--json"], capsys)

    assert rc == 0
    assert json.loads(out) == {"agents": built_frame["agents"], "boards": built_frame["boards"]}


def test_an_unknown_section_is_refused_with_the_frames_key_list(built_frame, capsys):
    rc, out = _run(["--only", "boards,no_such_section", "--json"], capsys)

    assert rc == 2
    envelope = json.loads(out)
    assert envelope["kind"] == "error"
    assert envelope["error"]["code"] == "invalid_request"
    assert envelope["error"]["reason"] == "unknown_snapshot_section"
    message = envelope["error"]["message"]
    assert "no_such_section" in message
    # The whole list survives — the caller corrects the request from it.
    assert all(key in message for key in built_frame)
    # Refused outright: the known half of the request is not served.
    assert "boards" not in envelope


def test_an_empty_selection_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        _parser().parse_args(["harness", "snapshot", "--only", " , ", "--json"])
    assert exit_info.value.code == 2


def test_the_text_line_is_unchanged_by_only(built_frame, capsys):
    rc, out = _run(["--only", "boards"], capsys)

    assert rc == 0
    assert out == "snapshot built (frame_source=built)\n"
