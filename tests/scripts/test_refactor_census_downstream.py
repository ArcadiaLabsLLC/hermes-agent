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


SEAM_MODULE = textwrap.dedent(
    """
    def zz_seam_by_ruling():
        return 1


    class Box:
        def zz_seam_method(self):
            return 2


    def zz_test_only_not_a_seam():
        return 3
    """
)

SEAMS_FILE = 'IN_MODULE_SEAMS = (\n    "mod.py::zz_seam_by_ruling",\n    "mod.py::Box.zz_seam_method",\n)\n'

TEST_FILE = "from mod import Box, zz_seam_by_ruling, zz_test_only_not_a_seam\n"


def test_an_in_module_seam_is_counted_as_a_seam_not_a_test_only_name(tmp_path):
    """Plan l5-17-test-only-names, bucket B: ``_seams.IN_MODULE_SEAMS`` takes a name off the DECIDE list."""

    (tmp_path / "mod.py").write_text(SEAM_MODULE, encoding="utf-8")
    (tmp_path / "files.txt").write_text("mod.py\n", encoding="utf-8")
    (tmp_path / "tests" / "_downstream").mkdir(parents=True)
    (tmp_path / "tests" / "_downstream" / "_seams.py").write_text(SEAMS_FILE, encoding="utf-8")
    (tmp_path / "tests" / "test_mod.py").write_text(TEST_FILE, encoding="utf-8")
    out = tmp_path / "out.json"
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "files.txt", str(out)],
        cwd=tmp_path, check=True, capture_output=True, timeout=60, text=True,
    )
    kinds = {r["name"]: r["kind"] for r in json.loads(out.read_text(encoding="utf-8"))["dead"]["mod.py"]}
    test_only = [line.split()[-2] for line in done.stdout.splitlines() if line.strip().startswith("TEST ")]

    assert kinds["zz_seam_by_ruling"] == "seam"
    assert kinds["Box.zz_seam_method"] == "seam"
    assert "zz_seam_by_ruling" not in test_only and "Box.zz_seam_method" not in test_only
    # Positive control: the same file's unlisted test-only name is still offered.
    assert kinds["zz_test_only_not_a_seam"] == "FunctionDef"
    assert "zz_test_only_not_a_seam" in test_only


def test_every_in_module_seam_names_a_live_attribute():
    """An allowlist entry that no longer resolves is a stale exemption, not a seam."""

    import importlib

    from tests._downstream._seams import IN_MODULE_SEAMS

    assert len(IN_MODULE_SEAMS) == len(set(IN_MODULE_SEAMS))
    for entry in IN_MODULE_SEAMS:
        path, _, qualname = entry.partition("::")
        target = importlib.import_module(path.removesuffix(".py").replace("/", "."))
        for part in qualname.split("."):
            target = getattr(target, part)
        assert callable(target), entry


WRAPPED_MODULE = textwrap.dedent(
    """
    import contextlib
    import functools
    from contextlib import contextmanager
    from dataclasses import dataclass


    @contextmanager
    def zz_ctx_helper():
        yield


    @contextlib.asynccontextmanager
    async def zz_async_ctx_helper():
        yield


    @functools.lru_cache(maxsize=None)
    def zz_cached_helper():
        return 1


    @dataclass
    class ZzRecord:
        value: int = 0


    class Box:
        @staticmethod
        def zz_static_helper():
            return 2

        @method("box.open")
        def zz_rpc_method(self):
            return 3


    @method("zz.verb")
    def zz_rpc_verb():
        return 4


    @router.get("/zz")
    def zz_route():
        return 5


    @doctor_check
    def zz_unknown_registry():
        return 6
    """
)


def test_a_wrapping_decorator_hides_nothing_and_a_registering_one_still_does(tmp_path):
    """Dead-code queue row (lane r-deadcode): `@contextmanager` hid `capture_create_subphases`.

    Each wrapping kind is judged by its name and offered; each registering kind (and an
    unknown decorator, the safe default) stays ``decorated``.
    """

    (tmp_path / "mod.py").write_text(WRAPPED_MODULE, encoding="utf-8")
    (tmp_path / "files.txt").write_text("mod.py\n", encoding="utf-8")
    out = tmp_path / "out.json"
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "files.txt", str(out)],
        cwd=tmp_path, check=True, capture_output=True, timeout=60, text=True,
    )
    kinds = {r["name"]: r["kind"] for r in json.loads(out.read_text(encoding="utf-8"))["dead"]["mod.py"]}
    dead = [line.split()[-2] for line in done.stdout.splitlines() if line.strip().startswith("DEAD ")]

    assert kinds["zz_ctx_helper"] == "FunctionDef"
    assert kinds["zz_async_ctx_helper"] == "AsyncFunctionDef"
    assert kinds["zz_cached_helper"] == "FunctionDef"
    assert kinds["ZzRecord"] == "ClassDef"
    assert kinds["Box.zz_static_helper"] == "method"
    for offered in ("zz_ctx_helper", "zz_async_ctx_helper", "zz_cached_helper", "ZzRecord", "Box.zz_static_helper"):
        assert offered in dead, offered
    for reached in ("Box.zz_rpc_method", "zz_rpc_verb", "zz_route", "zz_unknown_registry"):
        assert kinds[reached] == "decorated", reached
        assert reached not in dead, reached
