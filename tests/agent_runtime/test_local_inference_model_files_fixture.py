"""The local-inference model folders' file names, pinned for the Launcher (RT-LOCAL-MODEL-FIXTURES-FOR-LAUNCHER).

The Launcher's catalog entries for ``bge-small-en-v1.5`` and ``clip-vit-base-patch32`` place each
file of a model folder flat under the names :data:`EMBED_MODELS` / :data:`VISION_MODELS` list;
a folder short of one is ``model_partial``. ``tests/fixtures/local_inference_model_files.json`` is
that list as data, and the Launcher mirrors it beside its catalog, so a rename on either side reds
one of the two gates instead of shipping a catalog that installs an unloadable folder.

The expected side is BUILT from the tables (not a literal typed beside them): adding, dropping or
renaming a model or a file in ``models.py`` without the fixture reds here.
Killing mutation: rename ``vocab.txt`` to ``vocab.json`` in ``EMBED_MODELS`` -> red (recorded in the
commit that added this file).
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.local_inference.models import EMBED_MODELS, VISION_MODELS

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "local_inference_model_files.json"
_METHODS = (("runtime.embed.texts", EMBED_MODELS), ("runtime.vision.tag", VISION_MODELS))


def _from_tables() -> dict:
    return {spec.model: {"method": method, "files": list(spec.files)}
            for method, table in _METHODS for spec in table.values()}


def test_the_fixture_is_the_model_tables():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["schema"] == "hermes.local_inference_model_files/v1"
    assert fixture["models"] == _from_tables()


def test_every_file_is_a_flat_name():
    # A catalog places files flat in ``<models_dir>/<model>``; a separator would name a subfolder.
    for spec in (*EMBED_MODELS.values(), *VISION_MODELS.values()):
        assert spec.files and all("/" not in name and "\\" not in name for name in spec.files), spec.model
        assert len(set(spec.files)) == len(spec.files), spec.model
