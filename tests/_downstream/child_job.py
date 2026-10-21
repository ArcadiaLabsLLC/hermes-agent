"""No process a marked test starts outlives the test process, however it dies.

``tests/hermes_cli/test_completion_backlog.py`` (upstream) drives
``evals/completion_backlog_probe.probe``, which spawns up to twelve
``bash -lic`` -> ``python`` busy-waiters on a ``release`` file and writes the file
only after the last spawn; its ``finally`` kills them. pytest-timeout's ``thread``
method (the fork's, ``conftest_plugin.FORK_TEST_TIMEOUT_METHOD``) ends the process
with ``os._exit``, so no ``finally`` and no fixture teardown runs. Under
``scripts/run_tests.sh`` the per-file job wrapper (``scripts/_fork_runner.py``)
reaps them; under a direct ``python -m pytest`` 20-44 grandchildren outlived each
killed run, and 40 were found alive on 2026-10-18.

For a test carrying the mark, on Windows, the test process enters a kill-on-close
Job Object before the test body runs — the containment the runner's wrapper already
gives every test it runs. Children join it atomically at creation, and when the
process exits (``os._exit`` included) Windows kills every member still alive. The
handle is held for the rest of the process: closing it would kill the process too.
Upstream's bytes run unchanged.
"""

from __future__ import annotations

import sys

import pytest

from tests._downstream.id_markers.reasons import CHILDREN_DIE_WITH_THE_TEST_MARK

#: this process's job handle once entered (one per process; never closed)
_JOB: list = []


@pytest.hookimpl(specname="pytest_configure")
def pytest_configure_child_job(config):
    config.addinivalue_line(
        "markers",
        f"{CHILDREN_DIE_WITH_THE_TEST_MARK}: on Windows the test process is in a kill-on-close "
        "Job Object, so no child outlives a timeout's os._exit "
        "(tests/_downstream/child_job.py; applied by id from tests/_downstream/id_markers/).",
    )


@pytest.fixture(autouse=True)
def _children_die_with_the_test(request):
    if sys.platform != "win32" or request.node.get_closest_marker(CHILDREN_DIE_WITH_THE_TEST_MARK) is None:
        return
    if not _JOB:
        from scripts._fork_runner import enter_kill_on_close_job

        job = enter_kill_on_close_job()
        if job is None:
            pytest.fail("Windows refused a kill-on-close Job Object for the test process")
        _JOB.append(job)
