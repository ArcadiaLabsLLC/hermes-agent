"""Fork-owned tests moved out of ``tests/hermes_cli/test_doctor.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import io
import contextlib
from argparse import Namespace

from tests.hermes_cli.test_doctor import (  # noqa: F401 — upstream names the moved tests use
    _run_doctor,
)


class TestDoctorResolvesTheHomeAtCallTime:
    """The home doctor reports on is the one live when it RUNS.

    Red before the binding moved: ``HERMES_HOME`` was a module constant
    resolved at doctor's import, and under pytest that import happens at
    COLLECTION -- before the autouse hermetic-home fixture has redirected
    anything. Every path check below therefore read the operator's live store,
    which is why every other test in this file had to reach in and monkeypatch
    a production module's constant to be isolated at all.

    Asserted on a FILE the run has to have read, not on the printed home:
    ``_DHH`` is a separate, still-frozen label and asserting on it would only
    prove the label was patched.
    """

    @staticmethod
    def _hub(home, installed: int):
        hub = home / "skills" / ".hub"
        hub.mkdir(parents=True)
        (hub / "lock.json").write_text(
            '{"installed": {%s}}'
            % ", ".join(f'"skill{i}": {{}}' for i in range(installed)),
            encoding="utf-8",
        )

    def _run(self, monkeypatch, home):
        monkeypatch.setenv("HERMES_HOME", str(home))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _run_doctor(Namespace(fix=False))
        return buf.getvalue()

    def test_the_env_var_alone_redirects_every_profile_relative_read(
        self, monkeypatch, tmp_path
    ):
        home = tmp_path / "late-home"
        home.mkdir()
        self._hub(home, 3)

        out = self._run(monkeypatch, home)

        assert "Lock file OK (3 hub-installed skill(s))" in out

    def test_a_second_call_follows_a_second_home(self, monkeypatch, tmp_path):
        """One process, two homes -- the read cannot be cached anywhere."""
        first = tmp_path / "first"
        first.mkdir()
        self._hub(first, 1)
        second = tmp_path / "second"
        second.mkdir()
        self._hub(second, 7)

        assert "Lock file OK (1 hub-installed skill(s))" in self._run(
            monkeypatch, first
        )
        assert "Lock file OK (7 hub-installed skill(s))" in self._run(
            monkeypatch, second
        )
