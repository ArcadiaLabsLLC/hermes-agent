"""Public name for the named-profile listing.

A plugin that offers per-profile features needs the same list of live named
profiles the profile commands use (identity marker present, tombstones
skipped). The private spelling stays as an alias bound to the same object; the
profile commands read the public name, so overriding it is what takes effect.
"""

from types import SimpleNamespace

from hermes_cli import profiles


def test_public_name_is_the_private_helper():
    assert profiles.iter_named_profile_dirs is profiles._iter_named_profile_dirs


def test_overriding_iter_named_profile_dirs_reaches_list_profile_names(monkeypatch):
    monkeypatch.setattr(profiles, "iter_named_profile_dirs", lambda: [SimpleNamespace(name="zeta")])
    assert profiles.list_profile_names() == ["default", "zeta"]
