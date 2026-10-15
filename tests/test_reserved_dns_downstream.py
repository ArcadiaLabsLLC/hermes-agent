"""tests/_downstream/reserved_dns.py: fixture hosts fail fast, real names still resolve."""

from __future__ import annotations

import socket
import time

import pytest

from tests._downstream.reserved_dns import is_reserved_name


def test_the_session_runs_with_the_wrapper_installed():
    """Killing mutation: drop ``reserved_dns.install()`` from conftest_plugin.pytest_configure."""

    assert getattr(socket.getaddrinfo, "_fork_reserved_dns", False) is True


@pytest.mark.parametrize("host", ["new.example.test", "foo.invalid", "dashscope.example",
                                  "custom.meta.endpoint.internal", "x",
                                  "placeholder.services.ai.azure.com"])
def test_a_fixture_host_fails_fast_with_the_resolvers_own_answer(host):
    started = time.monotonic()
    with pytest.raises(socket.gaierror) as raised:
        socket.getaddrinfo(host, 443)
    assert raised.value.errno == socket.EAI_NONAME
    assert time.monotonic() - started < 1.0


def test_positive_control_localhost_and_ip_literals_reach_the_real_resolver():
    assert socket.getaddrinfo("localhost", 80)
    assert socket.getaddrinfo("127.0.0.1", 80)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "openrouter.ai", "api.example.com",
                                  "services.ai.azure.com", None, ""])
def test_real_names_and_literals_are_not_reserved(host):
    assert is_reserved_name(host) is False


def test_the_machines_own_single_label_name_is_not_reserved():
    assert is_reserved_name(socket.gethostname()) is False
