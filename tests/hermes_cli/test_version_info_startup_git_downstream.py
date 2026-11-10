"""Fork half of ``test_version_info_startup_git.py::test_startup_checkout_sha_read_is_one_rev_parse``.

Upstream (v0.23.1) pins the startup checkout-SHA read to exactly one ``git rev-parse HEAD``. The
fork's q-version seam (``hermes_cli.version_info_cache.memoize_run_git``) answers ``rev-parse HEAD``
from the git files themselves, so the same read spawns NO git: upstream's ``== ["rev-parse HEAD"]``
reads false. This runs upstream's own harness (a logging ``git`` shim on PATH, a fresh interpreter)
and pins the fork's answer: zero git calls, and the SHA git itself reports for the checkout.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from tests.hermes_cli.test_version_info_startup_git import _run_logging_git


@pytest.mark.platforms("linux", "macos")
def test_startup_checkout_sha_read_spawns_no_git(tmp_path):
    code = (
        "import json\n"
        "from hermes_cli.update_cmd_fleet import _current_checkout_sha\n"
        "from hermes_cli.version_info import _resolve_repo_dir\n"
        "sha = _current_checkout_sha()\n"
        "print(json.dumps({'sha': sha, 'repo': str(_resolve_repo_dir())}))\n"
    )
    result, calls = _run_logging_git(tmp_path, code)

    assert calls == []
    real_git = shutil.which("git")
    assert real_git is not None
    expected = subprocess.run([real_git, "-C", result["repo"], "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    assert result["sha"] == expected and len(expected) == 40
