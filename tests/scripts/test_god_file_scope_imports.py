"""``god_file_scope.import_nodes``: every import a full ``ast.walk`` finds, in its order, walked once.

Killing mutations (2026-11-10): drop ``ast.excepthandler`` from ``_STATEMENT_HOLDERS`` ->
``test_finds_the_imports_ast_walk_finds_in_its_order`` red (the ``except`` import is missed);
drop the ``held`` return in ``import_nodes`` -> ``test_a_tree_is_walked_once_and_not_kept_alive`` red;
make ``_IMPORTS`` a plain dict keyed by the tree -> the same test red (a cached tree outlives
``source_cache``'s eviction).
"""

from __future__ import annotations

import ast
import gc
import textwrap
import weakref

from scripts import god_file_scope

_SOURCE = textwrap.dedent(
    """
    import a
    try:
        import b
    except ImportError:
        import c
    else:
        from d import e
    finally:
        import f
    def g():
        import h
        class I:
            from j import k
    with open('x') as fh:
        import l
    match fh:
        case 1:
            import m
    if True:
        import n
    elif False:
        import o
    """
)


def _walk_imports(tree: ast.Module) -> list[ast.AST]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]


def test_finds_the_imports_ast_walk_finds_in_its_order():
    tree = ast.parse(_SOURCE)
    assert god_file_scope.import_nodes(tree) == _walk_imports(tree)
    assert len(_walk_imports(tree)) == 11


def test_a_tree_is_walked_once_and_not_kept_alive(monkeypatch):
    tree = ast.parse(_SOURCE)
    first = god_file_scope.import_nodes(tree)
    monkeypatch.setattr(god_file_scope.ast, "iter_child_nodes", lambda node: iter(()))
    assert god_file_scope.import_nodes(tree) is first
    monkeypatch.undo()
    alive = weakref.ref(tree)
    del tree, first
    gc.collect()
    assert alive() is None  # the cache holds no strong reference to a tree
