"""Missing provider SDKs: the Connections report and the one-extra install (w1015b-con-x).

OWNER RULING 2026-10-15: a missing SDK is a warning on the provider's Connections row,
fixed there by installing that one extra INTO the existing environment; a new
environment only on conflict; a sharing violation (os error 32) is waited out.
"""

from __future__ import annotations

import pytest

from agent_runtime import provider_dependencies as deps
from agent_runtime.provider_account import ProviderRefused
from hermes_cli import runtime_environment


def _missing(table: dict):
    """A stand-in keyed by provider, or by ``(provider, auth_mode)`` for a mode-only requirement."""
    return lambda *, provider=None, api_mode=None, model=None, auth_mode=None: list(
        table.get((provider, auth_mode) if auth_mode else provider, []))


@pytest.fixture
def sdks(monkeypatch):
    monkeypatch.setattr(deps, "_sdk_free", lambda: False)
    monkeypatch.setattr(deps, "_supported", lambda extra: True)

    def use(table):
        monkeypatch.setattr(runtime_environment, "missing_runtime_packages_for", _missing(table))
    return use


def test_the_report_names_each_provider_missing_its_sdk_and_the_extra_that_fixes_it(sdks):
    sdks({"anthropic": ["anthropic"], "openai": ["openai"]})
    report = deps.provider_dependency_report()
    assert report["sdk_free"] is False
    assert report["providers"] == [
        {"provider": "anthropic", "missing": ["anthropic"], "extra": "anthropic", "installable": True,
         "pack_available": False, "pack": None, "needed_when": None},
        # openai is a core dependency: no extra installs it, so no install is offered.
        {"provider": "openai", "missing": ["openai"], "extra": None, "installable": False,
         "pack_available": False, "pack": None, "needed_when": None},
    ]


def test_a_package_one_auth_mode_needs_is_reported_with_that_mode_and_never_blocks_a_turn(sdks):
    """Owner ruling 2026-10-16: ``runtime.provider.list`` reports azure-identity, which Azure
    Foundry needs only under ``model.auth_mode: entra_id``. The row names that mode; the pre-turn
    check (no mode named) never requires it, so an api-key Foundry turn is never refused for it.

    Killing mutation: drop the mode rows from ``_requirement_rows`` -> no azure-foundry row, red.
    Positive control: the api-key path (``required_packages_for`` without a mode) needs nothing."""
    sdks({("azure-foundry", "entra_id"): ["azure-identity"]})
    rows = {row["provider"]: row for row in deps.provider_dependency_report()["providers"]}
    assert rows["azure-foundry"] == {
        "provider": "azure-foundry", "missing": ["azure-identity"], "extra": "azure-identity",
        "installable": True, "pack_available": False, "pack": None, "needed_when": {"auth_mode": "entra_id"}}
    assert runtime_environment.required_packages_for(provider="azure-foundry") == []
    assert runtime_environment.required_packages_for(provider="azure-foundry", auth_mode="entra_id") == [
        "azure-identity"]


def test_the_mode_only_package_installs_its_one_extra(sdks):
    """The Developer Edition's install button on the azure-foundry row installs azure-identity.
    Killing mutation: ``_first_missing`` checks the hard table only -> ``already_installed``, red."""
    sdks({("azure-foundry", "entra_id"): ["azure-identity"]})
    extended = []
    result = deps.install_provider_dependency(
        "azure-foundry", extend=lambda reqs: extended.append(reqs) or True, new_generation=list)
    assert (result["extra"], result["outcome"]) == ("azure-identity", "installed")
    assert [item.split("==")[0] for item in extended[0]] == ["azure-identity"]


def test_the_phone_edition_reports_nothing_and_refuses_an_install(monkeypatch):
    """Positive control for the row above: same table, SDK-free profile -> nothing missing."""
    monkeypatch.setattr(deps, "_sdk_free", lambda: True)
    monkeypatch.setattr(runtime_environment, "missing_runtime_packages_for", _missing({"anthropic": ["anthropic"]}))
    assert deps.provider_dependency_report() == {"sdk_free": True, "providers": []}
    with pytest.raises(ProviderRefused) as refused:
        deps.install_provider_dependency("anthropic")
    assert refused.value.reason == "sdk_free_edition"


def test_the_extra_installs_into_the_existing_environment(sdks):
    sdks({"anthropic": ["anthropic"]})
    extended, built = [], []
    result = deps.install_provider_dependency(
        "anthropic", extend=lambda reqs: extended.append(reqs) or True, new_generation=built.append)
    assert result == {"provider": "anthropic", "extra": "anthropic", "outcome": "installed",
                      "environment": "existing", "restart_required": False}
    assert built == []
    assert [item.split("==")[0] for item in extended[0]] == ["anthropic"]


def test_a_conflicting_in_place_install_builds_a_new_environment(sdks):
    sdks({"anthropic": ["anthropic"]})
    built = []
    result = deps.install_provider_dependency("anthropic", extend=lambda reqs: False,
                                              new_generation=built.append)
    assert built == ["anthropic"]
    assert result["environment"] == "new" and result["restart_required"] is True


def test_a_held_file_is_reported_busy_not_rebuilt(sdks):
    from pm.package import InstallError

    sdks({"anthropic": ["anthropic"]})
    built = []

    def held(reqs):
        raise InstallError("venv", "uv pip install exited 2: failed to remove directory (os error 32)")

    with pytest.raises(ProviderRefused) as refused:
        deps.install_provider_dependency("anthropic", extend=held, new_generation=built.append)
    assert refused.value.reason == "environment_busy" and built == []


def test_a_present_sdk_installs_nothing(sdks):
    sdks({})
    result = deps.install_provider_dependency(
        "anthropic", extend=lambda reqs: pytest.fail("ran an install"),
        new_generation=lambda extra: pytest.fail("built an environment"))
    assert result["outcome"] == "already_installed"


def test_provider_list_carries_the_dependencies_block(sdks):
    from agent_runtime import provider_account

    sdks({"anthropic": ["anthropic"]})
    payload = provider_account.provider_list()
    assert "dependencies" not in payload.get("block_errors", {}), payload.get("block_errors")
    assert payload["dependencies"]["providers"][0]["provider"] == "anthropic"
