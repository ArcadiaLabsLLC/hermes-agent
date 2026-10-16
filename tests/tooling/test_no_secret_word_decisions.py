"""No fork module decides "is this a secret?" by looking for a secret WORD.

Plan ``docs/agent-runtime-harness/planned/redaction-one-value-redactor-2026-10-15.md``
S5. A word is not a secret; a value is. Three rounds retired word lists that
blanked ``token_budget.py`` and "the password field" while a ``ghp_`` token with
no word beside it went through (L2.21 ``a325b7c08e``, then this plan's S1-S4).
The one value test is ``agent_runtime.redaction`` (``scrub_secret_values``,
``has_secret_value``, ``scrub_display_text``).

NEGATIVE gate, so a source walk is the right instrument: it refuses
``any(marker in text for marker in <literal or module tuple of strings>)`` --
``all`` too -- when one of those strings carries a secret word. Over-approximation
is the safe direction. ``agent_runtime/redaction.py`` itself is exempt (it owns
the field-name tails, which are a key rule, not a text rule).
"""

from __future__ import annotations

import ast

from scripts import god_file_probe as probe

SECRET_WORDS = (
    "secret", "token", "password", "passwd", "api_key", "apikey", "api-key",
    "credential", "bearer", "authorization", "cookie", "private_key", "sk-",
)

#: ``path|function`` -> why it is allowed to stand. A row is a debt with a
#: queue row behind it, or a false positive with its reason.
ALLOWED = {
    "agent_runtime/workspace_slot_setup.py|classify_clone_failure": (
        "classifies git's own refusal text (\"could not read password\") into an end "
        "reason; nothing is hidden or shown by it"
    ),
}

_EXEMPT_PATHS = {"agent_runtime/redaction.py"}


def _string_members(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"frozenset", "set", "tuple"}:
        return _string_members(node.args[0]) if len(node.args) == 1 else None
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        members = [elt.value for elt in node.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
        return members if members else None
    return None


def _module_string_tuples(tree: ast.Module) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for stmt in tree.body:
        targets: list[ast.expr] = []
        value = None
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        members = _string_members(value) if value is not None else None
        if members:
            for target in targets:
                if isinstance(target, ast.Name):
                    found[target.id] = members
    return found


def _has_secret_word(members: list[str]) -> bool:
    return any(word in member.lower() for member in members for word in SECRET_WORDS)


def secret_word_decisions(source: str, path: str = "<src>") -> list[str]:
    """``path|function`` for every any()/all() over a secret-word tuple."""

    tree = ast.parse(source)
    tuples = _module_string_tuples(tree)
    hits: list[str] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            child_scope = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id in {"any", "all"}
                and len(child.args) == 1
                and isinstance(child.args[0], (ast.GeneratorExp, ast.ListComp, ast.SetComp))
            ):
                comp = child.args[0]
                is_membership = isinstance(comp.elt, ast.Compare) and any(
                    isinstance(op, (ast.In, ast.NotIn)) for op in comp.elt.ops
                )
                for generator in comp.generators:
                    iterable = generator.iter
                    members = (
                        tuples.get(iterable.id) if isinstance(iterable, ast.Name) else _string_members(iterable)
                    )
                    if is_membership and members and _has_secret_word(members):
                        hits.append(f"{path}|{scope}")
            visit(child, child_scope)

    visit(tree, "<module>")
    return sorted(set(hits))


def _census() -> set[str]:
    sites: set[str] = set()
    for path in probe.fork_production_files(probe.ROOT, probe.MANIFEST):
        if path in _EXEMPT_PATHS or not path.endswith(".py"):
            continue
        source = (probe.ROOT / path).read_text(encoding="utf-8")
        if "any(" not in source and "all(" not in source:
            continue
        sites.update(secret_word_decisions(source, path))
    return sites


def test_no_fork_module_decides_a_secret_by_a_word():
    new = sorted(_census() - set(ALLOWED))
    assert not new, (
        "a secret WORD decides what is shown here -- scrub the VALUE instead "
        "(agent_runtime.redaction.scrub_secret_values / has_secret_value / scrub_display_text):\n"
        + "\n".join(new)
    )


def test_an_allowed_site_that_is_gone_loses_its_row():
    stale = sorted(set(ALLOWED) - _census())
    assert not stale, "delete these ALLOWED rows -- the site is gone:\n" + "\n".join(stale)


def test_the_walk_sees_a_literal_a_module_tuple_and_a_frozenset_but_not_a_shape_rule():
    """Positive control: the four spellings the census must catch, one it must not."""

    source = (
        "_MARKERS = ('password', 'x')\n"
        "_SET = frozenset({'bearer '})\n"
        "def literal(t):\n    return any(m in t.lower() for m in ('secret', 'y'))\n"
        "def named(t):\n    return any(m in t for m in _MARKERS)\n"
        "def frozen(t):\n    return all(m not in t for m in _SET)\n"
        "def listcomp(t):\n    return any([m in t for m in ['sk-']])\n"
        "def shape(t):\n    return any(m in t for m in ('failed', 'timeout'))\n"
    )
    assert secret_word_decisions(source) == [
        "<src>|frozen", "<src>|listcomp", "<src>|literal", "<src>|named",
    ]
