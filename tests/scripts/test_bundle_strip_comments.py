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
