"""``runtime.provider.list``'s catalog rows carry ``auth_modes`` (RT-PROVIDER-AUTH-MODES).

Auth modes are hermes' fact: the launcher's sign-in asks for a mode only when a row names two
or more, and offers a mode-conditional pack (``needed_when.auth_mode``) for the chosen one.
"""

from hermes_cli.provider_login_catalog import PROVIDER_AUTH_MODES, provider_login_catalog
from hermes_cli.runtime_environment import _PROVIDER_MODE_PACKAGE_REQUIREMENTS


def test_azure_foundry_offers_api_key_and_keyless_entra_id():
    rows = {row["id"]: row for row in provider_login_catalog()}
    assert rows["azure-foundry"]["auth_modes"] == [
        {"id": "api_key", "label": "API key", "needs_key": True},
        {"id": "entra_id", "label": "Microsoft Entra ID", "needs_key": False},
    ]
    assert all(isinstance(row["auth_modes"], list) for row in rows.values())
    assert rows["anthropic"]["auth_modes"] == []


def test_every_mode_with_a_package_requirement_is_a_declared_auth_mode():
    for provider, modes in _PROVIDER_MODE_PACKAGE_REQUIREMENTS.items():
        declared = {mode for mode, _, _ in PROVIDER_AUTH_MODES.get(provider, ())}
        assert set(modes) <= declared, (provider, set(modes) - declared)


def test_the_provider_list_reply_carries_the_modes():
    from agent_runtime.provider_account import provider_list

    catalog = {row["id"]: row for row in provider_list()["catalog"]}
    assert [mode["id"] for mode in catalog["azure-foundry"]["auth_modes"]] == ["api_key", "entra_id"]
