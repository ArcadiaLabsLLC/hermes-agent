"""RT-MODEL-SELECT-CUSTOM-PROVIDER-UNCONFIRMED: a session on a Custom endpoint reports ``custom``,
the choice it was picked from is ``custom:<slug>``; the facts must name the choice's id."""
from agent_runtime.session_model_catalog import facts, model_key

INVENTORY = {"providers": [
    {"slug": "openrouter", "name": "OpenRouter", "models": ["m-1"]},
    {"slug": "qa-fixture", "name": "QA fixture", "is_user_defined": True, "models": ["local-7b"]},
]}


def test_a_custom_session_confirms_the_choice_it_was_picked_from():
    """Killing mutation: ``facts`` keyed on the raw ``info.provider`` -> current is ["custom","local-7b"], red."""
    result = facts("s1", {"info": {"provider": "custom", "model": "local-7b"}}, INVENTORY)
    assert result["current_model_id"] == model_key("custom:qa-fixture", "local-7b")
    assert result["current_model_id"] in {row["id"] for row in result["models"]}
    assert result["model_selection_required"] is False


def test_two_custom_endpoints_with_the_model_stay_unresolved():
    twice = {"providers": [*INVENTORY["providers"],
                           {"slug": "other", "name": "Other", "is_user_defined": True, "models": ["local-7b"]}]}
    result = facts("s1", {"info": {"provider": "custom", "model": "local-7b"}}, twice)
    assert result["current_model_id"] == model_key("custom", "local-7b")


def test_a_registered_provider_is_untouched():
    result = facts("s1", {"info": {"provider": "openrouter", "model": "m-1"}}, INVENTORY)
    assert result["current_model_id"] == model_key("openrouter", "m-1")
