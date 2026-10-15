"""Fork: ``pm.environments.main`` writes its exports as UTF-8 under any console codec.

Under a cp1252 console (Git Bash on Windows) a value the codec cannot encode
used to raise ``UnicodeEncodeError`` from ``print`` before any export was
written, and ``scripts/run_tests.sh`` then reported a missing environment.
"""

from __future__ import annotations

import io
import json
import sys

import pytest

import pm.environments as environments

VALUE = "/home/Łukasz/日本"


@pytest.mark.parametrize("dialect", ["sh", "json"])
def test_exports_survive_a_cp1252_console(monkeypatch, dialect):
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setattr(environments, "activation_environment", lambda _root: {"HOME_DIR": VALUE})

    environments.main(["--format", dialect])
    console.flush()

    written = raw.getvalue().decode("utf-8")
    if dialect == "sh":
        assert "/home/\u0141ukasz/\u65e5\u672c" in written
    else:
        assert json.loads(written) == {"HOME_DIR": VALUE}


def test_the_control_codec_really_cannot_encode_the_value():
    # Positive control: the fixture value is one cp1252 refuses.
    with pytest.raises(UnicodeEncodeError):
        VALUE.encode("cp1252")
