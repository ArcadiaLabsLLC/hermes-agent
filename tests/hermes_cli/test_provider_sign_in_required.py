"""The provider catalog says whether a provider needs a sign-in (RT-PROVIDER-CATALOG-SAYS-WHETHER-A-SIGN-IN-IS-NEEDED).

Eternia's composer warns over a signed-out provider only when this field is true, so a local
provider whose key is optional (LM Studio) or a keyless one (custom, the managed llamacpp runtime,
the ``moa`` virtual provider) must read false, and a provider that cannot answer without a stored
credential must read true. The field is decided in ONE place, ``sign_in_required_for``.
"""

from hermes_cli.provider_login_catalog import provider_login_catalog, sign_in_required_for


def _rows() -> dict[str, dict]:
    return {row["id"]: row for row in provider_login_catalog()}


def test_signed_in_providers_read_true_and_local_or_virtual_ones_false():
    rows = _rows()
    assert rows["anthropic"]["sign_in_required"] is True
    assert rows["openai-codex"]["sign_in_required"] is True
    assert rows["openrouter"]["sign_in_required"] is True
    for slug in ("custom", "lmstudio", "moa"):
        assert rows[slug]["sign_in_required"] is False, slug


def test_every_catalog_row_carries_the_field_as_a_bool():
    assert all(isinstance(row["sign_in_required"], bool) for row in _rows().values())


def test_the_managed_local_runtime_needs_no_sign_in():
    # llamacpp is a catalog row only when its server or a staged model exists; the decider is the
    # one owner either way.
    for alias in ("llamacpp", "llama.cpp", "llama-cpp"):
        assert sign_in_required_for(alias, "api_key", ()) is False


def test_cloud_sdk_and_oauth_providers_need_a_sign_in_without_a_key_var():
    assert sign_in_required_for("bedrock", "aws_sdk", ()) is True
    assert sign_in_required_for("xai-oauth", "oauth_external", ()) is True


def test_the_provider_list_reply_carries_the_field():
    from agent_runtime.provider_account import provider_list

    catalog = {row["id"]: row for row in provider_list()["catalog"]}
    assert catalog["anthropic"]["sign_in_required"] is True
    assert catalog["lmstudio"]["sign_in_required"] is False
