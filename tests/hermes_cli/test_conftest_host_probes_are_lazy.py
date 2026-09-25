"""The hermes_cli conftest's host prerequisite probe runs only for the files that need it.

``tests/_downstream/hermes_cli_conftest/`` is imported by every per-file
process under ``tests/hermes_cli``. Its web-build probe (a ``node --version``
spawn) used to run at import, in all ~1,260 of them, for the benefit of two
files. (A local-model port probe rode beside it until lane B5 deleted it: the
two tests it guarded were removed upstream in prune wave 2, ``39975613b1``,
and nothing checked that its ids still existed — the file check below does.) Lane SPEED, 2026-09-24:
`docs/agent-runtime-harness/planned/suite-cost-centres-2026-09-24.md`.

A session that collected none of those files must not have probed; one that
did must have probed exactly once.
"""

from tests._downstream import hermes_cli_conftest as conftest


def test_each_probe_ran_only_if_a_file_that_needs_it_was_collected(request):
    names = {item.path.name for item in request.session.items}
    web_needed = bool(names & set(conftest._WEB_BUILD_PREREQ_FILES))
    assert conftest._web_build_prereq_reason.cache_info().misses == int(web_needed)


def test_the_probe_names_are_the_files_that_consult_them():
    # Positive control for the negative above: these are the only keys the
    # collection hook probes for, and this file is not among them — so the
    # zero-miss reading is about laziness, not about a hook that never ran.
    assert __file__.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] not in conftest._WEB_BUILD_PREREQ_FILES
    assert "test_cmd_update.py" in conftest._WEB_BUILD_PREREQ_FILES


def test_every_prerequisite_file_still_exists():
    """A guard over a file upstream deleted guards nothing and reads like a fence.

    The local-model guard that stood beside this one named two tests gone since
    prune wave 2 and stayed unnoticed for weeks; this is the check it lacked.
    """
    from pathlib import Path

    here = Path(__file__).resolve().parent
    missing = sorted(name for name in conftest._WEB_BUILD_PREREQ_FILES if not (here / name).is_file())
    assert not missing, f"_WEB_BUILD_PREREQ_FILES names files that no longer exist: {missing}"
