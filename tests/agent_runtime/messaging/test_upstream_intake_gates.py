"""RT-MESSAGING-SHIM-STRANGER-GATE-HOLDS-ONLY-ON-TELEGRAM: no upstream adapter is wired into a serve without
its own intake gate and a test of it.

The shim's shared ``set_authorization_check`` is asked by some adapters' intake and not by others, so it is
not a gate alone. These pins hold the two places that close that: the base transport refuses to start with an
operator list and no per-adapter override, and every platform the serve lane can build an upstream adapter for
(``serve_lane.UPSTREAM_TRANSPORTS``) is listed in ``INTAKE_GATED`` with an override and an existing test that
drives that adapter's intake. Adding a platform's factory without both reds here.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime.messaging import serve_lane
from agent_runtime.messaging import upstream_adapter_transport as shim

REPO = Path(shim.__file__).resolve().parents[2]


def test_every_platform_the_serve_can_run_on_upstream_has_its_own_intake_gate_and_a_test_of_it():
    """Killing mutation: ``has_own_intake_gate`` drops the override comparison, or a platform's subclass loses
    its ``_install_intake_gate`` → red here (and the lane would wire the adapter in)."""
    assert serve_lane.UPSTREAM_TRANSPORTS, "no upstream platform to check"
    for platform in serve_lane.UPSTREAM_TRANSPORTS:
        cls = shim.INTAKE_GATED.get(platform.value)
        assert cls is not None, f"{platform.value}: no intake-gated transport"
        assert shim.has_own_intake_gate(cls), f"{platform.value}: {cls.__name__} has no intake gate of its own"
        test = REPO / cls.intake_gate_test
        assert test.is_file(), f"{platform.value}: {cls.intake_gate_test} is missing"
        assert cls.__name__ in test.read_text(encoding="utf-8"), f"{test.name} never drives {cls.__name__}"


def test_every_listed_transport_overrides_the_gate_and_names_a_real_test():
    for name, cls in shim.INTAKE_GATED.items():
        assert cls.platform == name and shim.has_own_intake_gate(cls)
        assert cls.__name__ in (REPO / cls.intake_gate_test).read_text(encoding="utf-8")


def test_the_generic_base_has_no_gate_of_its_own():
    assert not shim.has_own_intake_gate(shim.UpstreamAdapterTransport)
    assert not shim.has_own_intake_gate(None)

    class NoOverride(shim.UpstreamAdapterTransport):
        platform = "example"
        intake_gate_test = "tests/agent_runtime/messaging/test_upstream_intake_gates.py"

    assert not shim.has_own_intake_gate(NoOverride)


def test_the_base_refuses_to_start_with_an_operator_list_and_starts_nothing():
    """Killing mutation: ``start`` stops calling ``_install_intake_gate`` → the base starts with only the
    shared callback → no raise → red."""
    calls: list = []
    adapter = SimpleNamespace(config=SimpleNamespace(extra={}),
                              set_message_handler=lambda handler: calls.append("handler"),
                              set_authorization_check=lambda check: calls.append("check"))
    transport = shim.UpstreamAdapterTransport(adapter, connect=False, is_allowed=lambda user_id: True)
    before = {t.name for t in threading.enumerate()}
    with pytest.raises(RuntimeError, match="no intake gate"):
        transport.start(lambda update: None)
    assert calls == [] and transport._loop is None
    assert "messaging-upstream-adapter" not in {t.name for t in threading.enumerate()} - before
