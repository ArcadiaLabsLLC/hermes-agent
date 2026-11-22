"""Whether a module ships in this installation — the presence probe a profile's omissions answer.

A pure probe (``sys.modules`` + ``importlib.util.find_spec``), so any layer may ask it: a store or
a policy deciding whether a feature exists needs no lane. ``agent_runtime/loop_tool_lifecycles.py``
registers the placeholders this probe sees through, and re-exports both names
(RT-SHIPPED-PROBE-IN-LANES).

Two questions, never one for the other:

* :func:`shipped` — is the module importable here. An IMPORT guard asks it (a placeholder for an absent
  module, an optional import).
* :func:`runs_here` — does the feature run here: shipped AND not switched off by the installed bundle
  profile (``installed_profile``). A FEATURE gate asks it. A phone ships a switched-off module kept code
  imports unguarded (pinned), so ``shipped`` alone answers True there for a feature its profile switches
  off (RT-FU-A-PHONE-RUNS-A-FEATURE-ONLY-WHEN-ITS-PROFILE-SWITCHES-IT-ON;
  ``tests/agent_runtime/test_feature_gates_ask_the_profile.py`` refuses a feature gate's presence probe).
"""

from __future__ import annotations

import importlib.util
import sys

from .installed_profile import installed_switched_off

__layer__ = "models"  # a pure probe: the host resolver (models) asks it too
__all__ = ["BATCH_DISPATCHER_MODULES", "batch_dispatcher_runs_here", "is_lifecycle_placeholder", "runs_here", "shipped"]


def is_lifecycle_placeholder(module: object) -> bool:
    return bool(getattr(type(module), "__hermes_placeholder__", False))


def shipped(module: str) -> bool:
    """True when *module* is in this installation — importable, and not one of these placeholders.

    The presence test for a feature a profile leaves out of its wheel (``packaging.switched_off_modules``):
    the phone wheel omits the module, so the caller skips the step that would import it. Desktop and
    full Hermes ship every module, so there the answer is always True and the step runs as before.
    """
    loaded = sys.modules.get(module)
    if loaded is not None:
        return not is_lifecycle_placeholder(loaded)
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def runs_here(module: str) -> bool:
    """True when the feature *module* carries runs in this installation: the installed profile does not
    switch it off, and it ships. The question every feature gate asks; :func:`shipped` is the import guard's."""
    # MUTATION: drop the profile check -> test_feature_gates_ask_the_profile's runs_here case reddens.
    return not installed_switched_off(module) and shipped(module)


#: What ``agent_runtime.batch.dispatcher.default_dispatcher`` builds a serve's dispatcher from. The phone
#: bundle ships the ``agent_runtime.batch`` package (pinned: kept code imports ``dispatcher``, ``manifest``
#: and others at module level) but not ``board_source``, ``lander`` or ``lane_executor``, so the package's
#: presence is not the dispatcher's (RT-PHONE-WORK-ENGINE-START-FAILS-ON-A-MISSING-BATCH-MODULE). Asked
#: here, not in the package, so the probe never imports a package a profile switches off.
BATCH_DISPATCHER_MODULES = (
    "agent_runtime.batch.dispatcher",
    "agent_runtime.batch.board_source",
    "agent_runtime.batch.lander",
    "agent_runtime.batch.lane_executor",
)


def batch_dispatcher_runs_here() -> bool:
    """True when the serve's batch dispatcher runs here: every module it imports ships and none is switched off."""

    return all(runs_here(module) for module in BATCH_DISPATCHER_MODULES)
