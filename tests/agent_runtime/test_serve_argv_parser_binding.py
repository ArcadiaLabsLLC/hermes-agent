"""The serve argv lane borrows the harness parser through a BINDING, never an import.

No harness part may import ``hermes_cli.harness`` (W0-G6), so the lane's parser
builder is bound by the harness itself: ``hermes_cli.harness._cmd_serve`` hands
``build_parser`` to ``serve.commands._cmd_serve``, which binds it before the
loop starts. This file pins that production wiring — the session conftest binds
the same builder for every other test, so each test here starts UNBOUND.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from hermes_cli.harness_parts.serve import argv_lane
from hermes_cli.harness_parts.serve import commands as serve_commands


@pytest.fixture
def unbound(monkeypatch):
    monkeypatch.setattr(argv_lane, "_harness_parser_builder", None)


def test_an_unbound_lane_refuses_by_name(unbound):
    with pytest.raises(argv_lane.HarnessParserUnbound):
        argv_lane.dispatch_argv(["harness", "status"])


def test_the_harness_serve_verb_binds_its_own_parser_before_serving(unbound, monkeypatch):
    """Positive control on the production seam: ``hermes harness serve`` binds."""

    from hermes_cli import harness

    seen: dict = {}

    def _fake_serve_loop(reader, writer, **kwargs) -> int:
        seen["builder"] = argv_lane._harness_parser_builder
        return 0

    monkeypatch.setattr(
        serve_commands,
        "_claim_protocol_pipes",
        lambda: (os.open(os.devnull, os.O_RDONLY), os.open(os.devnull, os.O_WRONLY)),
    )
    monkeypatch.setattr(serve_commands, "serve_loop", _fake_serve_loop)

    code = harness._cmd_serve(SimpleNamespace(ndjson=True, pool_size=1, no_socket=True))

    assert code == 0
    assert seen["builder"] is harness.build_parser
