"""A child spawned with the SESSION's environment, run only as an explicit path.

Not a ``test_*`` file, so the suite never collects it; it is driven by
``tests/test_conftest_session_home_downstream.py`` as a nested bare
``python -m pytest`` launched from a shell carrying a stand-in "live" home.
"""

import os
import subprocess
import sys
from pathlib import Path

#: The environment as the session holds it outside any test (collection time):
#: what a session fixture, or a worker outliving its test, hands a child.
_SESSION_ENV = dict(os.environ)
_OUT = os.environ.get("SESSION_HOME_PROBE_OUT", "")
_REPO = Path(__file__).resolve().parents[2]

_CHILD = (
    "from hermes_constants import get_hermes_home\n"
    "home = get_hermes_home()\n"
    "(home / 'logs').mkdir(parents=True, exist_ok=True)\n"
    "with open(home / 'logs' / 'agent.log', 'a', encoding='utf-8') as log:\n"
    "    log.write('probe child\\n')\n"
    "print(home)\n"
)


def test_a_child_spawned_with_the_session_env():
    child = subprocess.run(
        [sys.executable, "-c", _CHILD], env=_SESSION_ENV, cwd=_REPO,
        capture_output=True, text=True, timeout=25,
    )
    assert child.returncode == 0, child.stderr
    Path(_OUT).write_text(child.stdout.strip(), encoding="utf-8")
