"""Fork half of ``test_web_server_ssh_media_stream.py::test_a_down_ssh_host_is_unavailable_to_the_stream``.

Upstream's body (v0.23.1) calls ``monkeypatch.undo()`` to drop its ``ssh`` fixture (the fake
``file_routes._fs_backend``) and then drives the real SSH backend against a down host. The fork
narrows a mid-body ``undo()`` to the body's own patches (``tests/_downstream/body_patch_scope.py``,
``scoped_monkeypatch_undo``) so fixtures' hermetic pins hold, and the fake backend therefore
survives the undo: the stream reads the host path and answers 404. The ``ssh`` fixture's state is
not something the body reads, so this runs upstream's own body WITHOUT that fixture: the real
``_fs_backend`` resolves the SSH host it configures and the stream answers 503. The body's
``undo()`` stays narrowed (it drops only the body's own patches), as the fork's suite requires.
"""

from __future__ import annotations

import pytest

from tests._downstream.id_markers.reasons import SCOPED_MONKEYPATCH_UNDO_MARK
from tests.hermes_cli import test_web_server_ssh_media_stream as upstream
from tests.hermes_cli.test_web_server_ssh_media_stream import client  # the fixture


# The body's undo() is upstream's, in another module, so the collection-time AST walk does not see
# it from here: mark it by hand, or the undo unwinds the suite's hermetic pins.
@getattr(pytest.mark, SCOPED_MONKEYPATCH_UNDO_MARK)
def test_a_down_ssh_host_is_unavailable_to_the_stream_without_the_fake_backend(client, monkeypatch):
    upstream.test_a_down_ssh_host_is_unavailable_to_the_stream(client, None, monkeypatch)
