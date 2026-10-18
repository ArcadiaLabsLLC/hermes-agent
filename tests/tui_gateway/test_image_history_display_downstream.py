"""RT-PHONE-HISTORY-IMAGE-IMPORT: a bundle without fastapi still loads a native-image history row.

The phone profile omits fastapi (``agent_runtime/bundle_profiles/bundled-phone.yaml``), so the
verifier's imports in ``tui_gateway/session_history.py::_user_image_display_text`` are
ImportError-guarded: the row keeps its stored text instead of raising out of the history load.
"""

import base64
import sys

from tui_gateway import server


def test_history_with_native_image_loads_when_fastapi_is_absent(tmp_path, monkeypatch):
    image = tmp_path / "shot.png"
    image.write_bytes(b"image bytes")
    url = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()
    parts = [{"type": "text", "text": f"Caption\n@image:{image}"},
             {"type": "image_url", "image_url": {"url": url}}]
    monkeypatch.setitem(sys.modules, "fastapi", None)  # `import fastapi` raises ImportError

    displayed = server._history_to_messages([{"role": "user", "content": parts}])

    assert len(displayed) == 1
    assert displayed[0]["role"] == "user"
    assert displayed[0]["text"].startswith("Caption")
