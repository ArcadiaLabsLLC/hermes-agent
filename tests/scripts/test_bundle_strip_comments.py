"""The phone bundle ships first-party modules without comments, line for line (RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT)."""

from __future__ import annotations

from pathlib import Path

from scripts.bundles.strip_comments import strip_comments

SOURCE = b'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Doc."""
# a comment line
x = 1  # trailing
s = "# not a comment"


def f():
    """Kept: code reads __doc__."""
    # inside
    return x + \\
        2
'''


def test_comments_go_and_every_line_stays_where_it_was():
    out = strip_comments(SOURCE)
    assert b"a comment line" not in out and b"trailing" not in out and b"inside" not in out
    assert out.count(b"\n") == SOURCE.count(b"\n")
    lines = out.split(b"\n")
    assert lines[0] == b"#!/usr/bin/env python3" and lines[1] == b"# -*- coding: utf-8 -*-"
    assert lines[4] == b"x = 1" and lines[5] == b's = "# not a comment"'
    assert b'"""Kept: code reads __doc__."""' in out
    namespace: dict = {}
    exec(compile(out, "m", "exec"), namespace)
    assert namespace["f"]() == 3 and namespace["f"].__doc__ == "Kept: code reads __doc__."


def test_a_file_the_tokenizer_cannot_read_ships_unchanged():
    broken = b"def f(:\n    # c\n"
    assert strip_comments(broken) == broken


def test_the_phone_profile_strips_and_the_desktop_profile_does_not(tmp_path: Path):
    from agent_runtime.bundle_profiles.manifest import load_profile
    from scripts.bundle_profile_package import _comment_free_copy

    assert load_profile("bundled-phone").packaging_strip_comments is True
    assert load_profile("bundled-desktop").packaging_strip_comments is False
    source = tmp_path / "m.py"
    source.write_bytes(SOURCE)
    _comment_free_copy(source, tmp_path / "out" / "m.py")
    assert b"a comment line" not in (tmp_path / "out" / "m.py").read_bytes()
    data = tmp_path / "d.yaml"
    data.write_bytes(b"# kept\na: 1\n")
    _comment_free_copy(data, tmp_path / "out" / "d.yaml")
    assert (tmp_path / "out" / "d.yaml").read_bytes() == b"# kept\na: 1\n"


def test_trailing_blanks_inside_a_string_are_kept():
    source = b'x = """a  \nb"""  # c\n'
    out = strip_comments(source)
    assert out == b'x = """a  \nb"""\n'


DOCSTRINGS = '''"""Module doc: argparse reads it."""


class Model:
    """Class doc: pydantic reads it."""

    def method(self):
        """Method doc,
        over two lines with é."""
        return 1


async def coro():
    """Coroutine doc."""


def one_liner(): "inline doc"


def tail():
    """Doc."""; return 2


def no_doc():
    return "not a docstring"
'''.encode()


def test_function_docstrings_empty_line_for_line_and_module_and_class_docstrings_stay():
    """Killing mutation: ``_function_docstring_spans`` also takes ``ast.ClassDef`` -> red (class doc gone)."""
    from scripts.bundles.strip_comments import strip_function_docstrings

    out = strip_function_docstrings(DOCSTRINGS)
    assert out.count(b"\n") == DOCSTRINGS.count(b"\n")
    assert b"Method doc" not in out and b"\xc3\xa9" not in out and b"Coroutine doc" not in out
    assert b"inline doc" not in out
    namespace: dict = {}
    exec(compile(out, "m", "exec"), namespace)
    assert namespace["__doc__"] == "Module doc: argparse reads it."
    assert namespace["Model"].__doc__ == "Class doc: pydantic reads it."
    assert namespace["Model"]().method() == 1 and namespace["Model"].method.__doc__ == ""
    assert namespace["tail"]() == 2 and namespace["tail"].__doc__ == "Doc."  # a statement after it: left alone
    assert namespace["no_doc"]() == "not a docstring"
    # each kept statement stays on its line: the method's `return` is still line 10
    assert out.split(b"\n")[9].strip() == b"return 1"


def test_the_phone_profile_empties_function_docstrings_and_the_desktop_profile_does_not(tmp_path: Path):
    """Killing mutation: the packager's copy ignores ``function_docstrings`` -> red."""
    from agent_runtime.bundle_profiles.manifest import load_profile
    from scripts.bundle_profile_package import _comment_free_copy

    assert load_profile("bundled-phone").packaging_strip_function_docstrings is True
    assert load_profile("bundled-desktop").packaging_strip_function_docstrings is False
    source = tmp_path / "m.py"
    source.write_bytes(DOCSTRINGS)
    _comment_free_copy(source, tmp_path / "plain" / "m.py")
    assert b"Method doc" in (tmp_path / "plain" / "m.py").read_bytes()  # positive control: flag off keeps it
    _comment_free_copy(source, tmp_path / "out" / "m.py", function_docstrings=True)
    assert b"Method doc" not in (tmp_path / "out" / "m.py").read_bytes()
