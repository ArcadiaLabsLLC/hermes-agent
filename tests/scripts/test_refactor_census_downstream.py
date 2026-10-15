"""``scripts/refactor_census.py`` judges a decorated function by its decorator, not its name.

Row L5.17 (queue-sweep 2026-10-10): 46 of 60 "DEAD" in the post-v0.21.6 census were
decorator-registered (singledispatch ``.register``, ``@method``, routes, ``@property``).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "refactor_census.py"

MODULE = textwrap.dedent(
    """
    import functools


    @functools.singledispatch
    def render(value):
        return str(value)


    @render.register
    def _render_int(value: int):
        return f"int {value}"


    class Card:
        @property
        def zz_title_only_via_attribute(self):
            return "t"

        def zz_plain_method_nobody_calls(self):
            return 1


    def zz_plain_function_nobody_calls():
        return 2
    """
)


def _census(tmp_path: Path) -> tuple[dict[str, str], str]:
    (tmp_path / "mod.py").write_text(MODULE, encoding="utf-8")
    (tmp_path / "files.txt").write_text("mod.py\n", encoding="utf-8")
    out = tmp_path / "out.json"
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "files.txt", str(out)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        timeout=60,
        text=True,
    )
    rows = json.loads(out.read_text(encoding="utf-8"))["dead"]["mod.py"]
    dead = [line.split()[-2] for line in done.stdout.splitlines() if line.strip().startswith("DEAD ")]
    return {r["name"]: r["kind"] for r in rows}, " ".join(dead)


def test_a_decorator_registered_function_is_not_a_dead_candidate(tmp_path):
    kinds, dead = _census(tmp_path)

    assert "_render_int" not in dead.split()
    assert "Card.zz_title_only_via_attribute" not in dead.split()

    assert kinds["_render_int"] == "decorated"
    assert kinds["Card.zz_title_only_via_attribute"] == "decorated"
    # Positive controls: the same file's undecorated, unreferenced defs stay candidates.
    assert kinds["zz_plain_function_nobody_calls"] == "FunctionDef"
    assert kinds["Card.zz_plain_method_nobody_calls"] == "method"
    assert "zz_plain_function_nobody_calls" in dead.split()
    assert "Card.zz_plain_method_nobody_calls" in dead.split()
