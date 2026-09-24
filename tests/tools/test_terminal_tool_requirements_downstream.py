"""Fork-owned tests moved out of ``tests/tools/test_terminal_tool_requirements.py``.

The upstream file keeps only upstream's tests; its autouse ``_clear_caches``
fixture is imported by name so it applies here too.
"""

from __future__ import annotations

import pytest

from tests.tools.test_terminal_tool_requirements import (  # noqa: F401 — upstream autouse fixture
    _clear_caches,
)


class TestCheckFnGraceReprobeBackoff:
    """The grace window must absorb a flake, not turn it into a storm.

    The suppression above originally implemented "do not cache the failure" as
    "do not cache anything", so every call inside the 60 s grace window re-ran
    the FULL probe -- subprocess, socket dial, SDK import -- and re-logged the
    transient warning. Measured on the operator's serve: 40 probes and 40
    warning lines in 2 s for one ``check_fn``, 759 such lines in one log, and
    the storm fired DURING the persona prewarm walk it was meant to make cheap.

    The gate counts PROBES and WARNINGS, never milliseconds: the cost this
    stage removes is "the probe body ran again", and a wall-clock budget on a
    probe whose body is ``return False`` would assert nothing. The clock is
    pinned so the arithmetic is exact rather than raced.
    """

    @staticmethod
    def _flaky_after_first_success():
        """A probe that succeeds once and fails forever after.

        Returns ``(probe, calls)`` where ``calls["n"]`` counts real bodies run
        -- exactly the number the storm inflated.
        """

        calls = {"n": 0}

        def probe():
            calls["n"] += 1
            return calls["n"] == 1

        return probe, calls

    @staticmethod
    def _transient_warnings(caplog):
        return [
            r.getMessage()
            for r in caplog.records
            if "treating as transient" in r.getMessage()
        ]

    def test_a_storm_of_calls_inside_the_grace_window_costs_one_probe(self, caplog):
        """40 calls in the window -- the live shape -- probe and warn ONCE."""
        import logging

        import tools.registry as reg

        probe, calls = self._flaky_after_first_success()
        t = {"now": 1000.0}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(reg.time, "monotonic", lambda: t["now"])
            assert reg._check_fn_cached(probe) is True  # records last-good
            assert calls["n"] == 1

            t["now"] += reg._CHECK_FN_TTL_SECONDS + 1  # expire the normal TTL
            with caplog.at_level(logging.WARNING, logger=reg.__name__):
                for _ in range(40):
                    # No clock movement between calls: this is the burst one
                    # check_fn takes from a single readiness/prewarm walk.
                    assert reg._check_fn_cached(probe) is True

        assert calls["n"] == 2, (
            "the grace window re-ran the full probe per call: "
            f"{calls['n'] - 1} probes for 40 calls"
        )
        warnings = self._transient_warnings(caplog)
        assert len(warnings) == 1, (
            "the transient warning fired once per call instead of once per "
            f"backoff interval: {len(warnings)} lines"
        )

    def test_the_backoff_expires_and_the_next_call_re_probes(self, caplog):
        """The backoff DELAYS the re-probe; it must never cancel it."""
        import logging

        import tools.registry as reg

        probe, calls = self._flaky_after_first_success()
        t = {"now": 1000.0}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(reg.time, "monotonic", lambda: t["now"])
            assert reg._check_fn_cached(probe) is True
            t["now"] += reg._CHECK_FN_TTL_SECONDS + 1
            with caplog.at_level(logging.WARNING, logger=reg.__name__):
                assert reg._check_fn_cached(probe) is True
                assert calls["n"] == 2
                # Still inside the backoff -> served from the cache entry.
                t["now"] += reg._CHECK_FN_GRACE_REPROBE_SECONDS / 2
                assert reg._check_fn_cached(probe) is True
                assert calls["n"] == 2
                # Past the backoff, still inside the grace window -> re-probe.
                t["now"] += reg._CHECK_FN_GRACE_REPROBE_SECONDS
                assert reg._check_fn_cached(probe) is True
                assert calls["n"] == 3, (
                    "the backoff never expired: a check_fn that fails forever "
                    "would be served from one stale probe for the whole window"
                )

        assert len(self._transient_warnings(caplog)) == 2

    def test_a_recovery_inside_the_window_is_cached_on_the_normal_ttl(self):
        """A backend that comes back must not stay on the 5 s backoff."""
        import tools.registry as reg

        state = {"ok": True}
        calls = {"n": 0}

        def probe():
            calls["n"] += 1
            return state["ok"]

        t = {"now": 1000.0}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(reg.time, "monotonic", lambda: t["now"])
            assert reg._check_fn_cached(probe) is True
            state["ok"] = False
            t["now"] += reg._CHECK_FN_TTL_SECONDS + 1
            assert reg._check_fn_cached(probe) is True  # grace-served
            assert calls["n"] == 2
            state["ok"] = True
            t["now"] += reg._CHECK_FN_GRACE_REPROBE_SECONDS + 0.5
            assert reg._check_fn_cached(probe) is True  # a real recovery
            assert calls["n"] == 3
            # A real True rides the full TTL, not the grace backoff.
            t["now"] += reg._CHECK_FN_GRACE_REPROBE_SECONDS + 0.5
            assert reg._check_fn_cached(probe) is True
            assert calls["n"] == 3, (
                "a recovered check_fn was re-probed on the grace backoff "
                "instead of the normal TTL"
            )

    def test_a_grace_true_never_outlives_the_grace_window(self):
        """Served at second 59, unreadable at second 61.

        The backoff is clamped to the grace window's end. Without the clamp a
        True served just before expiry would answer up to 5 s past it -- the
        cache extending the very window it is supposed to ride inside.
        """
        import tools.registry as reg

        probe, calls = self._flaky_after_first_success()
        t = {"now": 1000.0}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(reg.time, "monotonic", lambda: t["now"])
            assert reg._check_fn_cached(probe) is True
            # One second short of the grace window's end.
            t["now"] += reg._CHECK_FN_FAILURE_GRACE_SECONDS - 1
            assert reg._check_fn_cached(probe) is True
            assert calls["n"] == 2
            # Two seconds on, the grace window is over: the cached True must
            # not answer, and the honored failure must come through.
            t["now"] += 2
            assert reg._check_fn_cached(probe) is False
            assert calls["n"] == 3
