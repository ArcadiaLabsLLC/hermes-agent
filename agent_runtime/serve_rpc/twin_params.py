"""The keys each argv-twin method honours, for the manifest ``params`` block (owner ruling L4.22).

A ``models`` table so ``registry.manifest`` can read it without importing the
``lanes`` modules that register the methods. A row lists every key the handler reads.
"""

from __future__ import annotations

__layer__ = "models"

__all__ = ["CHARACTERS_METHOD_PARAMS", "TWIN_METHOD_PARAMS"]

#: ``runtime.characters.*`` (``serve_rpc/characters.py``).
CHARACTERS_METHOD_PARAMS: dict[str, tuple[str, ...]] = {
    "runtime.characters.list": (),
    "runtime.characters.status": ("draft",),
    "runtime.characters.thumb": ("attempt", "direction", "draft", "frame", "row", "scale", "square"),
    "runtime.characters.sprite": ("include_sheet", "slug"),
}

#: Every twin family's rows, merged; the manifest publishes this.
TWIN_METHOD_PARAMS: dict[str, tuple[str, ...]] = {**CHARACTERS_METHOD_PARAMS}
