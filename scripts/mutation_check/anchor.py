"""Pure text + AST: where a claim's ``find`` sits in its file today.

Resolves a claim's ``symbol`` against the module's real definitions, finds the
needle inside that span (verbatim, or re-indented by one constant), and hands
back a :class:`~scripts.mutation_check.schema.ClaimAnchor`. ``_read_source`` is
THE reader every offset in this package means. The map is
``scripts/mutation_check/__init__.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Callable, Mapping

from .schema import (
    BLOCK_STATEMENTS,
    MAX_REINDENT_COLUMNS,
    REPO_ROOT,
    WHOLE_MODULE_SYMBOLS,
    ClaimAnchor,
)

__layer__ = "policy"


def _qualified_definitions(tree: ast.Module) -> dict[str, list[ast.AST]]:
    """Every definition in the module, keyed by its dotted qualified name.

    Values are LISTS because a name can legitimately occur more than once in one
    module (a method spelled on two classes, a constant re-bound under a
    ``try``). An anchor over an ambiguous name is refused rather than guessed —
    guessing is how a claim ends up mutating a line in a symbol it does not
    name, which is the whole defect this anchoring replaces.

    **A block is not a naming scope, so the walk descends through it** (2026-09-02).
    ``try:`` / ``if:`` / ``with:`` / ``for:`` / ``while:`` / ``match:`` bodies
    carry no name of their own, so a ``def`` inside one belongs to whatever
    ``def``/``class`` encloses the block: ``serve_loop._drain_monitor`` is the
    helper `serve.py` defines inside a ``try:`` inside ``serve_loop``. Before
    this it was reachable by NO symbol — the claim had to name the outer
    function and say which line it meant in prose
    (``serve_loop/_drain_monitor terminal``), which hands the ``find`` the outer
    function's whole span and every sibling copy of the line in it. Every
    block-nested helper in the repo was unanchorable the same way.

    Python's own ``__qualname__`` spells these with a ``<locals>`` segment; this
    does not, because a claim's ``symbol`` is a thing a human types.
    """

    found: dict[str, list[ast.AST]] = {}

    def record(name: str, node: ast.AST) -> None:
        found.setdefault(name, []).append(node)

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            step = _WALK.get(type(child))
            if step is not None:
                step(child, prefix, record, walk)

    walk(tree, "")
    return found


Recorder = Callable[[str, ast.AST], None]
Walker = Callable[[ast.AST, str], None]


def _definition(child: ast.AST, prefix: str, record: Recorder, walk: Walker) -> None:
    qualified = prefix + child.name
    record(qualified, child)
    walk(child, qualified + ".")


def _assign(child: ast.AST, prefix: str, record: Recorder, walk: Walker) -> None:
    # Module- and class-level bindings are anchorable too: ``r1-
    # discriminator-weakened-to-a-bare-marker`` anchors on the
    # ``DELIBERATE_PLACEMENT_SUFFIX`` constant, which has no def line.
    for target in child.targets:
        if isinstance(target, ast.Name):
            record(prefix + target.id, child)


def _ann_assign(child: ast.AST, prefix: str, record: Recorder, walk: Walker) -> None:
    if isinstance(child.target, ast.Name):
        record(prefix + child.target.id, child)


def _descend(child: ast.AST, prefix: str, record: Recorder, walk: Walker) -> None:
    # Same prefix: the block adds nesting, not a name.
    walk(child, prefix)


#: What the definition walk does with each child node KIND. Looked up on
#: ``type(child)`` — a parsed tree never holds a subclass of a node class, so
#: that equals ``isinstance`` here; a kind with no row is walked past, as
#: before. ``BLOCK_STATEMENTS`` (``schema``) stays the vocabulary of block
#: kinds, and this table is its only reader.
_WALK: Mapping[type[ast.AST], Callable[[ast.AST, str, Recorder, Walker], None]] = {
    ast.FunctionDef: _definition,
    ast.AsyncFunctionDef: _definition,
    ast.ClassDef: _definition,
    ast.Assign: _assign,
    ast.AnnAssign: _ann_assign,
    **{block: _descend for block in BLOCK_STATEMENTS},
}


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _is_whole_module(symbol: str) -> bool:
    return symbol.split("/", 1)[0].strip().lower() in WHOLE_MODULE_SYMBOLS


def _symbol_span(text: str, path: str, symbol: str) -> tuple[int, int]:
    """The character span the claim's ``find`` is anchored INSIDE.

    ``symbol`` is ``<dotted definition>`` optionally followed by ``/<label>`` —
    the label is prose naming which line inside the definition the claim is
    about (``build_parser/work_list``) and is not resolved. The dotted half is
    resolved against the module's real definitions, and a bare method name is
    accepted when it is unambiguous, because that is how the claims that
    predate this anchoring are spelled.

    Until 2026-08-30 ``symbol`` was decorative: the needle was matched against
    the WHOLE FILE and nothing ever asked whether the named symbol existed.
    ``r1-create-stops-fencing-the-supplied-placement`` had named a deleted
    ``_parse_request`` for months while its guarantee was silently being
    exercised inside ``normalize_agent_create``.
    """

    if _is_whole_module(symbol):
        return 0, len(text)
    head = symbol.split("/", 1)[0].strip()
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        raise RuntimeError(
            f"symbol {head!r} cannot be resolved: {path} does not parse as Python "
            f"({error}); use symbol \"module\" for a file with no definitions"
        ) from error
    definitions = _qualified_definitions(tree)
    nodes = definitions.get(head, [])
    if not nodes:
        # A bare name, matched as a suffix of a qualified one: ``upsert_actor``
        # resolves to ``OfficeStore.upsert_actor`` when that is the only one.
        nodes = [
            node
            for qualified, candidates in definitions.items()
            if qualified.endswith("." + head)
            for node in candidates
        ]
    if not nodes:
        raise RuntimeError(f"symbol not found in {path}: {head}")
    if len(nodes) > 1:
        raise RuntimeError(
            f"symbol is ambiguous in {path}: {head} resolves {len(nodes)} times; "
            "qualify it (Class.method)"
        )
    node = nodes[0]
    offsets = _line_offsets(text)
    end_lineno = getattr(node, "end_lineno", None) or node.lineno
    return offsets[node.lineno - 1], offsets[min(end_lineno, len(offsets) - 1)]


def _reindent(block: str, shift: int, *, shift_first_line: bool) -> str | None:
    """``block`` with every line's own indentation moved by ``shift`` columns.

    RELATIVE indentation is preserved by construction — every line moves by the
    same amount — so this recognises a block that was dedented out of a ``try``
    or indented into one, and does NOT recognise a block whose internal nesting
    changed. That is the point: a re-indent is the same code in a new place, a
    re-nest is different code.

    ``None`` when the shift is not expressible: a tab-indented line (columns are
    not a fact about tabs) or a line that would need negative indentation.
    """

    out: list[str] = []
    for index, line in enumerate(block.split("\n")):
        if not line.strip():
            out.append(line)
            continue
        if index == 0 and not shift_first_line:
            out.append(line)
            continue
        stripped = line.lstrip(" \t")
        lead = line[: len(line) - len(stripped)]
        if "\t" in lead:
            return None
        width = len(lead) + shift
        if width < 0:
            return None
        out.append(" " * width + stripped)
    return "\n".join(out)


def _candidate_offsets(span: str, needle: str) -> dict[int, tuple[int, bool]]:
    """Every place in ``span`` the claim's block could be, as ``offset → (shift, at_line_start)``.

    TWO spellings, and the split between them is what keeps a re-indent from
    swallowing a re-NEST:

    * verbatim, and only at shift 0 — today's exact match, kept whole so a claim
      that still reads byte-for-byte is never re-interpreted. It may land
      mid-line, which is how a sub-line needle anchors at all.
    * line-start, at any shift — the whole block re-indented by one constant,
      matched only where a line begins. The first line moves WITH the rest,
      which is precisely what makes relative nesting a fixed property: a block
      whose inner line gained a level relative to its opener has no constant
      shift and drops out.

    Leaving the first line verbatim while shifting the others (the third
    spelling, which the first draft had) is the bug both of those avoid — it
    matches any re-nesting at all, and re-indents the replacement wrong.
    """

    found: dict[int, tuple[int, bool]] = {}
    exact = needle
    position = span.find(exact)
    while position != -1:
        found[position] = (0, False)
        position = span.find(exact, position + 1)
    if found:
        return found
    for size in range(1, MAX_REINDENT_COLUMNS + 1):
        for shift in (-size, size):
            moved = _reindent(needle, shift, shift_first_line=True)
            if moved is None:
                continue
            position = span.find(moved)
            while position != -1:
                if position == 0 or span[position - 1] == "\n":
                    found.setdefault(position, (shift, True))
                position = span.find(moved, position + 1)
        if found:
            # The smallest shift that explains the block wins; a larger one that
            # also matched would be a different block wearing the same shape.
            break
    return found



def _anchor_claim(text: str, claim: dict[str, Any]) -> ClaimAnchor:
    path = str(claim["path"])
    symbol = str(claim["symbol"])
    start, end = _symbol_span(text, path, symbol)
    span = text[start:end]
    needle = str(claim["find"])

    candidates = _candidate_offsets(span, needle)
    if not candidates:
        raise RuntimeError(
            f"mutation source not found in {path}::{claim['symbol']}"
            + _reanchor_hint(text, path, needle)
        )
    if len(candidates) > 1:
        raise RuntimeError(
            f"mutation source must occur exactly once in {path}::{claim['symbol']}; "
            f"found {len(candidates)}"
        )
    position, (shift, shift_first_line) = next(iter(candidates.items()))
    moved_find = _reindent(needle, shift, shift_first_line=shift_first_line)
    moved_replace = _reindent(str(claim["replace"]), shift, shift_first_line=shift_first_line)
    assert moved_find is not None
    if moved_replace is None:
        raise RuntimeError(
            f"{claim['id']}: the replacement cannot follow the anchor's {shift:+d}-column shift"
        )
    offset = start + position
    first = text.count("\n", 0, offset) + 1
    if _is_whole_module(symbol):
        symbol_lines: frozenset[int] = frozenset()
    else:
        symbol_lines = frozenset(
            range(text.count("\n", 0, start) + 1, text.count("\n", 0, end) + 2)
        )
    return ClaimAnchor(
        offset=offset,
        lines=set(range(first, first + moved_find.count("\n") + 1)),
        find=moved_find,
        replace=moved_replace,
        shift=shift,
        symbol_lines=symbol_lines,
    )


def _reanchor_hint(text: str, path: str, needle: str) -> str:
    """Name the symbol the needle DID land in, when the claim's symbol missed.

    A stale ``symbol`` is now fatal, so the error has to carry the repair: the
    two ways a claim goes stale are a rename and an extraction, and both leave
    the guarantee sitting in a symbol this can point at.
    """

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ""
    offsets = _line_offsets(text)
    holders: list[str] = []
    for qualified, nodes in _qualified_definitions(tree).items():
        for node in nodes:
            # Definitions only. A binding that IS the needle would name itself
            # back at the reader, and "re-anchor onto holder.limit" is not a
            # repair anybody can act on.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            end_lineno = getattr(node, "end_lineno", None) or node.lineno
            body = text[offsets[node.lineno - 1] : offsets[min(end_lineno, len(offsets) - 1)]]
            if _candidate_offsets(body, needle):
                holders.append(qualified)
    if not holders:
        return ""
    innermost = max(holders, key=lambda name: name.count("."))
    return f"; it is in {innermost} — re-anchor the claim's symbol"


def _read_source(target: Path) -> tuple[bytes, str]:
    """The file's raw bytes, and THE text every offset in this module means.

    One reader, because the two that existed disagreed about line endings and
    the disagreement was silent until it wasn't. ``_anchor_or_raise`` used
    ``read_text`` (universal newlines: a CRLF file decodes with LF) while the
    mutate loop used ``read_bytes().decode()`` (raw, CRLF kept), so against a
    CRLF-committed file every anchor offset was one byte short per preceding
    line and the splice refused with "changed after the anchor resolved" —
    measured red on pristine `main` (`0c744aa586`) on a Windows host, and
    reachable on Linux too, since 25 tracked `.py` blobs carried CRLF and a
    checkout of those is CRLF everywhere.

    LF is the normal form on both sides: claims register their ``find`` with
    LF, so anchoring a CRLF file at all requires it. The mutant is written LF
    and the original bytes are restored in ``finally`` regardless, so a
    deliberately-CRLF file is never left rewritten by a run.
    """

    raw = target.read_bytes()
    return raw, raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _anchor_or_raise(claim: dict[str, Any]) -> tuple[ClaimAnchor, str]:
    target = REPO_ROOT / str(claim["path"])
    if not target.is_file():
        raise RuntimeError(f"{claim['id']}: target missing: {claim['path']}")
    _, text = _read_source(target)
    try:
        return _anchor_claim(text, claim), text
    except RuntimeError as error:
        raise RuntimeError(f"{claim['id']}: {error}") from error
