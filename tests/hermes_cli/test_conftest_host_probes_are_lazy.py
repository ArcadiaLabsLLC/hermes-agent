"""The hermes_cli conftest's two host probes run only for the files that need them.

``tests/_downstream/hermes_cli_conftest.py`` is imported by every per-file
process under ``tests/hermes_cli``. Its web-build probe (a ``node --version``
spawn) and its local-model probe (a connect to 127.0.0.1:11434, a 2 s timeout
on a host that drops the SYN) used to run at import, in all ~1,260 of them,
for the benefit of three files. Lane SPEED, 2026-09-24:
`docs/agent-runtime-harness/planned/suite-cost-centres-2026-09-24.md`.

A session that collected none of those files must not have probed; one that
did must have probed exactly once.
"""

from tests._downstream import hermes_cli_conftest as conftest


def test_each_probe_ran_only_if_a_file_that_needs_it_was_collected(request):
    names = {item.path.name for item in request.session.items}
    local_needed = bool(names & set(conftest._LOCAL_MODEL_PROBE_NODE_IDS))
    web_needed = bool(names & set(conftest._WEB_BUILD_PREREQ_FILES))
    assert conftest._local_model_probe_reason.cache_info().misses == int(local_needed)
    assert conftest._web_build_prereq_reason.cache_info().misses == int(web_needed)


def test_the_probe_names_are_the_files_that_consult_them():
    # Positive control for the negative above: these are the only keys the
    # collection hook probes for, and this file is not among them — so the
    # zero-miss reading is about laziness, not about a hook that never ran.
    assert __file__.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] not in (
        set(conftest._LOCAL_MODEL_PROBE_NODE_IDS) | set(conftest._WEB_BUILD_PREREQ_FILES)
    )
    assert "test_timeouts.py" in conftest._LOCAL_MODEL_PROBE_NODE_IDS
    assert conftest._WEB_BUILD_PREREQ_FILES
