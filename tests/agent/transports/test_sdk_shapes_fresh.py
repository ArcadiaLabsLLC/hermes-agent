"""``agent/transports/sdk_shapes.py`` is exactly what ``scripts/gen_sdk_shapes.py`` renders from the SDKs.

The SDK-free clients build the SDKs' objects from that table; a stale table is a silent
divergence (a field the SDK types that ours leaves raw, or omits from ``model_dump``). The
rendering walks the installed SDKs' pydantic models, so this test is the runtime answer to
"does the table match the SDK", not a spelling comparison.

Killing mutation (applied, red recorded, reverted — see the commit message): delete one field
from one ``KINDS`` row of the committed table -> red.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("openai")
pytest.importorskip("anthropic")

REPO = Path(__file__).resolve().parents[3]


def _generator():
    spec = importlib.util.spec_from_file_location("gen_sdk_shapes", REPO / "scripts" / "gen_sdk_shapes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_shapes_are_the_installed_sdks():
    generator = _generator()
    rendered = generator.render()
    assert rendered == generator.TARGET.read_text(encoding="utf-8"), "run scripts/gen_sdk_shapes.py"
    assert "'anthropic.ToolUseBlock'" in rendered and "'openai.Response'" in rendered  # control: both SDKs walked
