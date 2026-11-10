"""An ssh profile's REMOTE working directory is a POSIX path, whatever host the gateway runs on.

Upstream's ``tui_gateway/session_workdir.py::_is_remote_cwd_shape`` judges it with the host's ``os.path.isabs``. On
Windows under Python >= 3.13 ``ntpath.isabs("/home/kali")`` is False (a rooted path without a drive is no longer
absolute), so ``_completion_cwd`` drops a named ssh profile's remote cwd to ``~`` and ``_workspace_cwd`` refuses it
(``session.workspace.move`` -> 4017). Row RT-SSH-PROFILE-REMOTE-CWD, owner ruling 2026-11-10: fixed here, in fork
code, never by editing the upstream file.

The split modules' bodies are rebound onto server.py's namespace (``tui_gateway/method_ctx.bind_module``), so every
caller looks ``_is_remote_cwd_shape`` up in server.py's globals at call time. :func:`register` runs after that
binding (``agent_runtime.gateway_extensions.register``) and wraps the bound name: upstream's verdict still stands,
and a POSIX-absolute path is accepted too. On a POSIX host the wrapper changes nothing.
"""
from __future__ import annotations

import posixpath

__layer__ = "lanes"


def register(server) -> None:
    upstream_shape = server._is_remote_cwd_shape

    def _is_remote_cwd_shape(raw: str) -> bool:
        return upstream_shape(raw) or posixpath.isabs(raw)

    _is_remote_cwd_shape.__doc__ = upstream_shape.__doc__
    _is_remote_cwd_shape.__wrapped__ = upstream_shape
    server._is_remote_cwd_shape = _is_remote_cwd_shape
