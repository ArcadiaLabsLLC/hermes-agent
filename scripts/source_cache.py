"""One read and one ``ast.parse`` per file per process, shared by every whole-tree walker.

The whole-tree gates (``docs/agent-runtime-harness/11-gate-directory.md`` § Cost) each
read and parsed the tree on their own; a bundle that ran two of them paid the parse
twice. They now ask this module for a file's text (:func:`source`) and its tree
(:func:`tree`), so the second walker in a process reads the first one's parse.

* Keyed on the absolute path AND the file's ``(mtime_ns, size)``: a file a test writes
  and rewrites (a tmp tree) is re-read, never served stale.
* Text is kept for the process (the whole tracked tree is ~130 MB of source; a string
  is not a GC object). A tree is KEPT only when the caller asks (``keep=True``): a
  parsed module holds ~20x its source in AST objects, every one GC-tracked, and a
  process holding them pays for them on every full collection -- measured 2026-10-18,
  the coverage-claims walk took 41.7 s of CPU keeping its trees against 22.5 s not
  keeping them (and retaining every tree once pushed a 13 s gate past its timeout,
  ``tests/agent_runtime/_tree_index.py``, 2026-09-01). So a walker that comes back to a
  file (the god-file gates' scope questions, the s55 emitter index) keeps, least-
  recently-used under :data:`TREE_BUDGET_BYTES` of source; a single-pass walker
  (``keep=False``) reads a kept tree when one is there and otherwise parses and lets go.
* A returned tree is SHARED: read it (``ast.walk``), never mutate or annotate it. A
  walker that rewrites a tree parses its own copy.
* A file that does not parse is ``None`` (cached); a ``SyntaxWarning`` from an upstream
  file's regex literal is the parse's noise, not a walker's finding, and is silenced.
* Undecodable bytes are replaced (``errors="replace"``), the mode every walker used.

:func:`stats` counts reads, parses and hits, so a gate can prove the sharing happened.
"""

from __future__ import annotations

import ast
import os
import warnings
from collections import OrderedDict

#: Source bytes of parsed trees kept at once (~1.3 GB of AST objects at the measured ratio).
TREE_BUDGET_BYTES = 64 * 1024 * 1024

_Key = tuple[str, int, int]
_SOURCES: dict[str, tuple[_Key, str]] = {}
_TREES: OrderedDict[_Key, ast.Module | None] = OrderedDict()
_TREE_BYTES: dict[_Key, int] = {}
_COUNTS = {"reads": 0, "read_hits": 0, "parses": 0, "parse_hits": 0}
_held = 0


def _key(path: os.PathLike[str] | str) -> _Key:
    name = os.path.normcase(os.path.abspath(os.fspath(path)))
    st = os.stat(name)
    return name, st.st_mtime_ns, st.st_size


def source(path: os.PathLike[str] | str) -> str:
    """The file's text, decoded UTF-8 with undecodable bytes replaced; read once per version."""
    key = _key(path)
    cached = _SOURCES.get(key[0])
    if cached is not None and cached[0] == key:
        _COUNTS["read_hits"] += 1
        return cached[1]
    with open(key[0], encoding="utf-8", errors="replace", newline=None) as handle:
        text = handle.read()
    _COUNTS["reads"] += 1
    _SOURCES[key[0]] = (key, text)
    return text


def tree(path: os.PathLike[str] | str, *, keep: bool = True) -> ast.Module | None:
    """The file's module tree; ``None`` when it does not parse. Kept (``keep``) trees are
    parsed once per version and served to every later caller."""
    global _held
    key = _key(path)
    if key in _TREES:
        _TREES.move_to_end(key)
        _COUNTS["parse_hits"] += 1
        return _TREES[key]
    text = source(path)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            parsed: ast.Module | None = ast.parse(text, filename=key[0])
    except (SyntaxError, ValueError):
        parsed = None
    _COUNTS["parses"] += 1
    if not keep:
        return parsed
    _TREES[key] = parsed
    _TREE_BYTES[key] = len(text)
    _held += len(text)
    while _held > TREE_BUDGET_BYTES and len(_TREES) > 1:
        old, _ = _TREES.popitem(last=False)
        _held -= _TREE_BYTES.pop(old)
    return parsed


def stats() -> dict[str, int]:
    """Reads, parses and the hits that skipped them, since the process started (or :func:`clear`)."""
    return dict(_COUNTS)


def clear() -> None:
    """Forget every text and tree (a test that measures the cache starts from empty)."""
    global _held
    _SOURCES.clear()
    _TREES.clear()
    _TREE_BYTES.clear()
    _held = 0
    for name in _COUNTS:
        _COUNTS[name] = 0
