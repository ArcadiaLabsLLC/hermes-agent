"""Fork-owned tests moved out of ``tests/hermes_cli/test_config_read_guard.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations


from tests.hermes_cli.test_config_read_guard import (  # noqa: F401 — upstream names the moved tests use
    _offenders,
)


#: A raw read the guard must report: a ``safe_load`` within ``PROXIMITY`` lines
#: of a ``"config.yaml"`` reference, in a file no allowlist entry covers.
_RAW_READ_SOURCE = 'import yaml\n\nyaml.safe_load(open("config.yaml"))\n'


def test_the_walk_does_not_descend_into_a_repo_copy(tmp_path):
    """``.claude/worktrees/<branch>/`` is a FULL COPY of this repo (B20(iii)).

    Driven on a synthetic tree rather than on this checkout, because the hazard
    is intermittent: worktrees exist while agents are running and are pruned
    afterwards, so a witness that waited for the real thing would be a check
    that passes for the wrong reason most of the time — and it passed for the
    wrong reason for the fortnight this guard was red.

    Both directions in one case. The copy's file is invisible; the identical
    file OUTSIDE the excluded directory is reported. Without the control, an
    exclusion set that had swallowed the whole walk would look like a fix.
    """

    copy = tmp_path / ".claude" / "worktrees" / "wave-2" / "gateway"
    copy.mkdir(parents=True)
    (copy / "config.py").write_text(_RAW_READ_SOURCE, encoding="utf-8")

    first_party = tmp_path / "some_package"
    first_party.mkdir()
    (first_party / "reader.py").write_text(_RAW_READ_SOURCE, encoding="utf-8")

    offenders = _offenders(tmp_path)

    assert [entry.split(":")[0] for entry in offenders] == [
        "some_package/reader.py"
    ], (
        "the walk reported a different offender set than expected. If it "
        "contains a path under `.claude/`, the exclusion is gone and every "
        "repo-wide scan is again reading this repository's own copies of "
        f"itself. Offenders: {offenders}"
    )
