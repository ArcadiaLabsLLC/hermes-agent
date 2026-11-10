"""``hermes_user_agent`` reads the cached release (FH-FOOTPRINT-PROVIDER-UA-LAZY, RULED owner 2026-11-10).

The fork rebinds upstream's ``hermes_user_agent`` to ``release_version`` in version_info's fork block,
so the provider plugins keep upstream's bytes and still build their User-Agent from the cached read.

Killing mutation (2026-11-10): drop the ``hermes_user_agent = _release_user_agent`` line -> red (the
provenance walk's ``base_version`` answers instead of the release read).
"""

from hermes_cli import version_info


def test_the_user_agent_is_the_cached_release(monkeypatch):
    monkeypatch.setattr(version_info, "release_version", lambda: "9.9.9-release")
    monkeypatch.setattr(version_info, "get_version_info",
                        lambda: (_ for _ in ()).throw(AssertionError("the provenance walk ran")))
    assert version_info.hermes_user_agent("HermesAgent") == "HermesAgent/9.9.9-release"
    assert version_info.hermes_user_agent() == "hermes-cli/9.9.9-release"
