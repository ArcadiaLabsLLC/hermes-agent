"""Every upstream-red row names an upstream test that exists (design sweep D3.13).

``tests/_downstream/id_markers/upstream_reds.py`` and ``upstream_reds_v0216.py``
mark upstream's own Windows reds by node id. The collection-time stale check
(``id_markers/hooks.py``) refuses a missing id only when its file is collected,
and the tables are host-filtered (empty off Windows), so a renamed or deleted
upstream test could leave a dead row nobody collects. This gate reads every row
from the tables' SOURCE (any host) and resolves it without collecting the tree:
the file is in ``tests/fixtures/upstream_manifest.txt`` and exists, and its
``ast`` defines the test (in the named class, or a base class defined in the
same file). Parametrize ids (``[...]``) are not resolved; the function is.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_TABLES = (
    _REPO / "tests" / "_downstream" / "id_markers" / "upstream_reds.py",
    _REPO / "tests" / "_downstream" / "id_markers" / "upstream_reds_v0216.py",
    _REPO / "tests" / "_downstream" / "id_markers" / "upstream_reds_v0217.py",
    _REPO / "tests" / "_downstream" / "id_markers" / "upstream_reds_v0222.py",
)
_MANIFEST = _REPO / "tests" / "fixtures" / "upstream_manifest.txt"


def _is_node_id(text) -> bool:
    return isinstance(text, str) and text.startswith("tests/") and ".py::" in text


def _expand_comprehension(comp: ast.DictComp) -> list[str]:
    """``{f"tests/x.py::{test}": … for test in ("a", "b")}`` → the two ids."""

    key, gen = comp.key, comp.generators[0] if comp.generators else None
    if not (isinstance(key, ast.JoinedStr) and gen and isinstance(gen.target, ast.Name)):
        return []
    if not isinstance(gen.iter, (ast.Tuple, ast.List)):
        return []
    ids = []
    for item in gen.iter.elts:
        if not (isinstance(item, ast.Constant) and isinstance(item.value, str)):
            return []
        text = ""
        for part in key.values:
            if isinstance(part, ast.Constant):
                text += str(part.value)
            elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name) and part.value.id == gen.target.id:
                text += item.value
            else:
                return []
        ids.append(text)
    return ids


def table_node_ids(source: str) -> list[str]:
    """Every row id in ``source``: string constants that read as node ids, and the
    ids an f-string dict comprehension spells over a literal tuple."""

    tree = ast.parse(source)
    in_fstring = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values}
    ids = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and id(node) not in in_fstring and _is_node_id(node.value):
            ids.append(node.value)
        elif isinstance(node, ast.DictComp):
            ids.extend(i for i in _expand_comprehension(node) if _is_node_id(i))
    return ids


def _defined_tests(tree: ast.Module) -> tuple[set[str], dict[str, tuple[set[str], list[str]]]]:
    functions = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    classes = {}
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        methods = {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        bases = [b.id for b in cls.bases if isinstance(b, ast.Name)]
        classes[cls.name] = (methods, bases)
    return functions, classes


def unresolved(node_ids, repo: Path, manifest: set[str]) -> list[str]:
    """The ids whose file is not upstream, is missing, or does not define the test."""

    parsed: dict[str, tuple] = {}
    bad = []
    for node_id in node_ids:
        path, _, rest = node_id.partition("::")
        parts = [part.split("[", 1)[0] for part in rest.split("::")]
        file = repo / path
        if path not in manifest or not file.is_file():
            bad.append(f"{node_id}  (file not upstream or missing)")
            continue
        if path not in parsed:
            parsed[path] = _defined_tests(ast.parse(file.read_text(encoding="utf-8")))
        functions, classes = parsed[path]
        if len(parts) == 1:  # a module-level test, or a whole class
            ok = parts[0] in functions or parts[0] in classes
        else:
            ok, seen, queue = False, set(), [parts[0]]
            while queue and not ok:
                name = queue.pop()
                if name in seen or name not in classes:
                    continue
                seen.add(name)
                methods, bases = classes[name]
                ok = parts[-1] in methods
                queue.extend(bases)
        if not ok:
            bad.append(f"{node_id}  (test not defined)")
    return bad


def _manifest() -> set[str]:
    return {
        line.strip() for line in _MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def test_every_upstream_red_row_resolves_to_an_upstream_test():
    manifest = _manifest()
    ids = [node_id for table in _TABLES for node_id in table_node_ids(table.read_text(encoding="utf-8"))]
    assert len(ids) > 250, f"the table walk found only {len(ids)} ids — the walk is wrong"

    bad = unresolved(ids, _REPO, manifest)

    assert not bad, "upstream-red rows that name no upstream test:\n" + "\n".join(bad)


def test_a_renamed_test_is_caught():
    """Positive control: a real row pointed at a name the file does not define."""

    manifest = _manifest()
    real = table_node_ids(_TABLES[0].read_text(encoding="utf-8"))[0]
    renamed = real.rsplit("::", 1)[0] + "::test_renamed_away_by_upstream"

    assert unresolved([real], _REPO, manifest) == []
    assert unresolved([renamed], _REPO, manifest) == [f"{renamed}  (test not defined)"]
