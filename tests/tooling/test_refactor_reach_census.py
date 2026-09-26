"""The reach census's static-reach pre-filter (lane Q-DEAD-B, 2026-09-25).

``scripts/refactor_reach_census.py`` files a DECIDE row for code the traced
suite never ran. Lane Q-DEAD-A refuted 45 of 45 such rows: each had a
production reference the tracer cannot see. The pre-filter strikes a function
row when the fork tree registers it, passes it as a value, calls it from its
own file, or imports it and uses it — and tags rows in files that run in a
child process. Every arm below is proven by a POSITIVE control (the same tree,
one reference removed, and the row must be filed again).
"""

from __future__ import annotations

import ast
from pathlib import Path

from scripts import god_file_probe as probe
from scripts import refactor_reach_census as census

DEAD = "def {name}(x):\n" + "".join(f"    x = x + {i}\n" for i in range(10)) + "    return x\n"


def _tree(tmp_path: Path, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return sorted(files)


def _strike(tmp_path: Path, files: dict[str, str], path: str, name: str) -> str | None:
    index = census.ReachIndex(tmp_path, _tree(tmp_path, files))
    tree = probe._tree(tmp_path, path)
    unit = next(u for u in probe.iter_units(path, tree) if u.node.name == name)
    return index.strike(path, unit.qualname, unit.node)


def test_a_parser_registered_handler_is_struck_and_its_control_is_filed(tmp_path):
    handler = DEAD.format(name="_cmd_thing")
    registered = {"pkg/cmds.py": handler, "pkg/parser.py": "def build(p):\n    p.set_defaults(func=_cmd_thing)\n"}
    assert _strike(tmp_path / "a", registered, "pkg/cmds.py", "_cmd_thing") == f"{census.ARM_REGISTERED}: pkg/parser.py"
    bare = {"pkg/cmds.py": handler, "pkg/parser.py": "def build(p):\n    p.set_defaults(verbose=True)\n"}
    assert _strike(tmp_path / "b", bare, "pkg/cmds.py", "_cmd_thing") is None


def test_a_registering_decorator_strikes_and_a_wrapping_one_does_not(tmp_path):
    body = DEAD.format(name="handle")
    registered = {"m.py": "@method('ping')\n" + body}
    assert _strike(tmp_path / "a", registered, "m.py", "handle").startswith(census.ARM_REGISTERED)
    wrapped = {"m.py": "@functools.lru_cache(maxsize=None)\n" + body}
    assert _strike(tmp_path / "b", wrapped, "m.py", "handle") is None


def test_a_callable_passed_as_a_keyword_is_struck(tmp_path):
    files = {"a.py": DEAD.format(name="_prewarm"), "b.py": "def boot(run):\n    run(provider_prewarm=_prewarm)\n"}
    assert _strike(tmp_path / "a", files, "a.py", "_prewarm") == f"{census.ARM_PASSED}: b.py:2"
    files["b.py"] = "def boot(run):\n    run(provider_prewarm=None)\n"
    assert _strike(tmp_path / "b", files, "a.py", "_prewarm") is None


def test_an_own_file_call_strikes_and_recursion_alone_does_not(tmp_path):
    called = {"s.py": DEAD.format(name="_helper") + "\n\nif __name__ == '__main__':\n    _helper(1)\n"}
    assert _strike(tmp_path / "a", called, "s.py", "_helper").startswith(census.ARM_OWN_CALL)
    recursive = {"s.py": DEAD.format(name="_helper").replace("    return x\n", "    return _helper(x)\n")}
    assert _strike(tmp_path / "b", recursive, "s.py", "_helper") is None


def test_an_import_strikes_only_when_the_importer_uses_the_name(tmp_path):
    lib = DEAD.format(name="shared")
    used = {"pkg/lib.py": lib, "pkg/use.py": "from pkg.lib import shared\n\ndef go():\n    return shared(1)\n"}
    assert _strike(tmp_path / "a", used, "pkg/lib.py", "shared") is not None
    reexport = {"pkg/lib.py": lib, "pkg/__init__.py": "from pkg.lib import shared\n__all__ = ['shared']\n"}
    assert _strike(tmp_path / "b", reexport, "pkg/lib.py", "shared") is None
    via_module = {"pkg/lib.py": lib, "use.py": "from pkg import lib as L\n\ndef go():\n    return L.shared(1)\n"}
    assert _strike(tmp_path / "c", via_module, "pkg/lib.py", "shared") == f"{census.ARM_IMPORTED}: use.py:4"


def test_child_process_trees_and_main_guarded_scripts_are_tagged(tmp_path):
    files = {
        "hermes_cli/harness_parts/serve/boot.py": "X = 1\n",
        "scripts/tool.py": "def main():\n    return 0\n\nif __name__ == '__main__':\n    main()\n",
        "agent_runtime/plain.py": "X = 1\n",
    }
    index = census.ReachIndex(tmp_path, _tree(tmp_path, files))
    assert "serve child process" in index.entry("hermes_cli/harness_parts/serve/boot.py")
    assert "__main__" in index.entry("scripts/tool.py")
    assert index.entry("agent_runtime/plain.py") is None


def test_a_struck_row_is_listed_apart_and_never_counted_as_filed(tmp_path):
    files = {"m.py": DEAD.format(name="live") + "\n" + DEAD.format(name="dead") + "\nVALUE = live\n"}
    index = census.ReachIndex(tmp_path, _tree(tmp_path, files))
    rows = census.rows_for(tmp_path, "m.py", set(), index)
    by_name = {r.unit: r for r in rows}
    assert by_name["live"].struck and not by_name["dead"].struck
    text = census.render(rows, [], 1, 0, 0)
    head, _, struck = text.partition("## struck by static reach")
    assert "live function" not in head and "dead function" in head
    assert "live function" in struck and census.ARM_PASSED in struck


def test_the_fixture_function_is_long_enough_to_be_a_row():
    """The fixtures above only mean something if an unreached DEAD is a census row at all."""
    node = ast.parse(DEAD.format(name="f")).body[0]
    assert (node.end_lineno - node.lineno + 1) >= census.MIN_UNIT_LINES
