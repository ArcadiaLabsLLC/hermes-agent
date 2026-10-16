"""``redaction.mask_local_paths`` and ``has_secret_value``: the path policy and
the value test every display lane shares (plan redaction-one-value-redactor S3)."""

from __future__ import annotations

import pytest

from agent_runtime.redaction import has_secret_value, mask_local_paths


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("opened /home/alice/proj/notes.txt to check", "opened …/notes.txt to check"),
        (r"opened C:\Users\alice\proj\notes.txt, ok", "opened …/notes.txt, ok"),
        ("C:/Users/alice/notes.txt", "…/notes.txt"),
        ("~/proj/notes.txt", "…/notes.txt"),
        ("//server/share/alice/f.txt", "…/f.txt"),
        ("(/etc/alice/passwd)", "(…/passwd)"),
    ],
)
def test_an_absolute_path_is_shortened_to_its_last_segment(text, shown):
    assert mask_local_paths(text) == shown
    assert mask_local_paths(shown) == shown  # idempotent


@pytest.mark.parametrize(
    "text",
    [
        "edited agent_runtime/token_budget.py",
        "see https://example.test/a/b?x=1",
        "run /help now",
        "1/2 and/or",
        "approx ~5 minutes",
    ],
)
def test_relative_paths_urls_and_prose_are_kept(text):
    assert mask_local_paths(text) == text


def test_a_path_under_a_root_becomes_root_relative():
    assert mask_local_paths(r"C:\Repo\src\a.py failed", roots=("c:/repo",)) == "src/a.py failed"
    assert mask_local_paths("/srv/repo/src/a.py", roots=("/srv/repo/",)) == "src/a.py"


def test_has_secret_value_reads_values_not_words():
    assert has_secret_value("pushed with ghp_" + "A1" * 12) is True
    assert has_secret_value("password=" + "hunter" + "Two" * 4) is True
    assert has_secret_value("token_budget.py caps the password field") is False
