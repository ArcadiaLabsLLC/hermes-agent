"""The phone bundle's REAL closure and profile gate, over the real profile and the real tree
(RT-PHONE-PACKAGER-TESTS-NEVER-RUN-THE-REAL-CLOSURE).

The packager and gate tests beside this file pin pure decisions over stubbed plans, so the phone
build broke unseen for 25 days (``RT-PHONE-BUNDLE-NEEDS-TWO-LIBRARIES-IT-LEAVES-OUT``: upstream
modules the phone keeps imported pydantic / fastapi unguarded). Here nothing is stubbed: the
gate (``scripts/bundle_profile_gate.py::gate``) walks ``bundled-phone`` once and plans each of its
``packaging.targets`` with the packager's own closure facts (``scripts/bundle_profile_closure.py``
``WalkFacts`` / ``GraphFacts``, the ones ``bundle_profile_package.py``'s seed plan refuses with).

Two holds:

* a closure refusal on any phone target is a red at once (the packager would exit 1);
* the gate's findings, per kind, sit under :data:`CEILING`, a shrink-only ratchet: a new refusal
  is a red, and a fixed one is a red until its count here is lowered (never raised; the work list
  is the gate's own ``--markdown`` report).

Measured 2026-11-16 on the Linux box: the module fixture runs the gate in 1m54s
(``closure()`` per target took 5m23s cold before the gate shared one walk).
"""

from __future__ import annotations

from collections import Counter

import pytest

from agent_runtime.bundle_profiles.manifest import load_profile

PROFILE = "bundled-phone"

#: The gate's one real walk runs in the first test's setup (1m54s measured; the runner's per-test
#: default is 60s). Under the runner's 300s per-file cap.
pytestmark = pytest.mark.timeout(280)

#: ``tests/_downstream/child_site/sitecustomize.py::ENV`` (that directory is a ``site`` dir, not a package).
CHILD_STARTUP_ENV = "HERMES_TEST_CHILD_STARTUP"

#: Shrink-only: the gate's findings per kind over every phone target, read 2026-11-16 once the
#: phone closure built again (the 2 ``closure`` findings gone). Lower a number when a refusal is
#: fixed; never raise one — a new refusal is fixed, or switched off in the profile.
CEILING = {
    "browser": 9,
    "pinned": 2,
    "subprocess_call": 22,
}


@pytest.fixture(scope="module")
def phone_gate() -> dict:
    """The gate's probe children run without the suite's child start-up shortcut: its after-import
    finder and the spawn stand-ins' rebinding finder each delegate to every other finder, so with
    both installed a stand-in module's import recurses until RecursionError (seen 2026-11-16)."""
    import os

    from scripts.bundle_profile_gate import gate

    saved = os.environ.pop(CHILD_STARTUP_ENV, None)
    try:
        return gate(PROFILE)
    finally:
        if saved is not None:
            os.environ[CHILD_STARTUP_ENV] = saved


def test_the_gate_plans_every_phone_target_the_profile_names(phone_gate):
    targets = load_profile(PROFILE).packaging_targets
    assert len(targets) >= 2
    assert sorted(phone_gate["targets"]) == sorted(targets)


def test_no_phone_target_refuses_its_closure(phone_gate):
    """An omitted library (pydantic, fastapi, …) imported unguarded by a kept module refuses here."""
    refused = [(target, finding["subject"]) for target, row in phone_gate["targets_detail"].items()
               for finding in row["findings"] if finding["kind"] == "closure"]
    assert refused == []


def test_the_gates_findings_stay_under_their_shrink_only_ceiling(phone_gate):
    counts = dict(Counter(finding["kind"] for finding in phone_gate["refusals"]))
    over = {kind: (n, CEILING.get(kind, 0)) for kind, n in counts.items() if n > CEILING.get(kind, 0)}
    assert over == {}, f"new phone gate refusals (count, ceiling): {over}"
    under = {kind: (counts.get(kind, 0), n) for kind, n in CEILING.items() if counts.get(kind, 0) < n}
    assert under == {}, f"refusals fixed — lower CEILING to the count (count, ceiling): {under}"
