"""The per-test Hermes home carries a ``config.yaml`` stamped with the current config version (h1-setup).

``tests/conftest.py::_hermetic_environment`` mints ``<tmp_path>/hermes_test`` with no
``config.yaml``. Upstream ``hermes_cli.config._load_config_impl`` caches on the file's
signature, and an absent file has none: every ``load_config_readonly()`` in such a home
deep-copies, canonicalises and env-expands ``DEFAULT_CONFIG`` again (8-10 ms of CPU under
the chain, measured 2026-10-18). ``SessionDB`` pays two per open (``resolve_journal_mode``,
``apply_database_pragmas``): 418 rebuilds, 3.4 s of ``test_hermes_state.py``'s setup.

The file carries ONLY ``_config_version`` at the current ``DEFAULT_CONFIG`` value, so the
merged config is exactly the defaults and ``migrate_config`` finds nothing to do (an empty
``{}`` reds ``test_config.py::test_migrate_reports_normalized_line_formatting`` with
"Config version: 0 -> 50"). A test that writes its own ``config.yaml`` overwrites it; a test
that points ``HERMES_HOME`` at its own directory is untouched.

``hermes_cli.config`` is never imported for a test (import order is some tests' subject): a
test that has not loaded it yet gets no file.

The home sits inside the test's ``tmp_path``, so a test whose subject is that directory gets
no file (``BARE_HOME_FILES``): one that ``git init``s ``tmp_path`` and reads its status, and
one that proves no ROOT config exists before it writes one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def stamped_config_text(config_module) -> str | None:
    version = (getattr(config_module, "DEFAULT_CONFIG", None) or {}).get("_config_version")
    if not isinstance(version, int):
        return None
    return f"_config_version: {version}\n"


#: Test files whose subject is the bare ``tmp_path`` the home sits in (land h1018).
BARE_HOME_FILES = frozenset({
    "tests/agent_runtime/test_dirty_state.py",
    "tests/agent_runtime/test_root_config_hermetic.py",
})


@pytest.fixture(autouse=True)
def _home_carries_a_config(request, _hermetic_environment):
    if Path(str(request.node.path)).as_posix().split("/tests/", 1)[-1] in {
            name.split("tests/", 1)[1] for name in BARE_HOME_FILES}:
        return
    config_module = sys.modules.get("hermes_cli.config")
    if config_module is None:
        return
    text = stamped_config_text(config_module)
    home = os.environ.get("HERMES_HOME")
    if text is None or not home:
        return
    path = Path(home) / "config.yaml"
    if path.parent.is_dir() and not path.exists():
        path.write_text(text, encoding="utf-8")
