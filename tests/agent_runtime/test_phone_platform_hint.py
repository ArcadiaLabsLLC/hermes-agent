"""The phone agent is told its limits (plan Stage 5, owner ruling 2026-09-28), and the text is
derived from the phone profile's disabled toolsets rather than written by hand.
"""

from __future__ import annotations

import dataclasses

from agent_runtime.bundle_profiles.manifest import known_toolset_names, load_profile
from agent_runtime.bundle_profiles.phone_hint import CAPABILITIES, phone_platform_hint


def test_the_phone_hint_upstream_serves_is_the_one_derived_from_the_phone_profile():
    from agent.prompt_builder import PLATFORM_HINTS
    from agent.system_prompt import _default_platform_hint

    derived = phone_platform_hint(load_profile("bundled-phone"))
    assert PLATFORM_HINTS["phone"] == derived
    assert _default_platform_hint("phone") == derived
    for phrase in ("no shell or terminal", "no background processes",
                   "no file system beyond this app's own sandbox", "needs the desktop"):
        assert phrase in derived


def test_turning_a_toolset_back_on_removes_its_sentence_and_nothing_else():
    manifest = load_profile("bundled-phone")
    with_shell = dataclasses.replace(
        manifest, disabled_toolsets=tuple(t for t in manifest.disabled_toolsets if t != "terminal"))

    hint = phone_platform_hint(with_shell)

    assert "no shell or terminal" not in hint
    assert "no background processes" not in hint  # process_manage rides the terminal toolset
    assert "no code execution" in hint and "no file system beyond" in hint


def test_every_capability_names_real_toolsets():
    """A renamed toolset must not leave a capability that can never be reported absent."""
    known = known_toolset_names()
    assert [t for toolsets, _ in CAPABILITIES for t in toolsets if t not in known] == []
