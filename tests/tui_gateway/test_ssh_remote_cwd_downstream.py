"""An ssh profile's remote working directory is judged as a POSIX path on every host.

Row RT-SSH-PROFILE-REMOTE-CWD: upstream's ``_is_remote_cwd_shape`` uses the host's ``os.path.isabs``, and on Windows
under Python >= 3.13 ``ntpath.isabs("/home/kali")`` is False. The fork wraps the bound name in
``agent_runtime.gateway.ssh_remote_cwd`` (installed by ``agent_runtime.gateway_extensions.register``).
"""
from types import SimpleNamespace

import pytest

from agent_runtime.gateway import ssh_remote_cwd


def _wrapped(upstream_verdict: bool):
    server = SimpleNamespace(_is_remote_cwd_shape=lambda raw: upstream_verdict)
    ssh_remote_cwd.register(server)
    return server._is_remote_cwd_shape


@pytest.mark.parametrize("raw", ["/home/kali", "/", "/srv/work dir"])
def test_posix_absolute_remote_dir_is_accepted_where_the_host_refuses_it(raw):
    # The upstream stub answers like ntpath.isabs on Python >= 3.13, whatever host this runs on.
    assert _wrapped(False)(raw) is True


@pytest.mark.parametrize("raw", ["relative/dir", "kali", "C:relative", ""])
def test_relative_remote_dir_stays_refused(raw):
    assert _wrapped(False)(raw) is False


def test_upstream_acceptance_still_stands():
    assert _wrapped(True)("~") is True


def test_live_gateway_accepts_a_posix_remote_workspace(monkeypatch):
    from tui_gateway import server

    assert server._is_remote_cwd_shape.__module__ == ssh_remote_cwd.__name__
    monkeypatch.setattr(server, "_cwd_is_remote", lambda profile_home: True)
    assert server._workspace_cwd(None, "/home/kali/project") == "/home/kali/project"
    with pytest.raises(ValueError):
        server._workspace_cwd(None, "project")
