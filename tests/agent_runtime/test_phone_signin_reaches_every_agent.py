"""A provider signed in on a phone is offered in every agent's chat model list.

Seen live 2026-11-20 on the owner's phone (Eternia row
``MC-PHONE-AGENT-CANNOT-PICK-A-MODEL-FROM-A-PROVIDER-SIGNED-IN-ON-THE-PHONE``): Connections read
"ChatGPT or Codex Subscription — Connected" after the device-code sign-in, yet an agent's chat
greyed every Codex model — ``runtime.operator.conversation.models`` offered none.

Cause, reproduced here: Android hands the app ``/data/user/0/<app>``, a link to ``/data/data/<app>``.
The sign-in writes ``auth.json`` under the Hermes home as the host spelled it; an agent with its
own profile reads its sign-ins at the shared-auth home, which
``agent_runtime.provider_credentials.bound_provider_home`` RESOLVES — the real path. The host
store bound its root as spelled, so the agent's path lay "outside the store root": no slot, no
sign-in. The fix is the binding's one path identity (``host_store.binding.canonical_path``):
the root and every slot are keyed by real location, so both spellings name one slot.

The app folder below is reached through a link (a junction on Windows, a symlink elsewhere),
the phone's shape. POSITIVE CONTROLS: the same agent through the real path is offered Codex,
and so is an agent without a profile of its own — the scenario is only red where the phone was.

Killing mutation (applied, red recorded, reverted): key the root and the slot by
``Path(os.path.abspath(...))`` instead of ``canonical_path`` in ``bind_host_store`` and
``HostStoreBinding.relative`` (the binding before this fix) — ``[True-linked]`` reddens with
``assert 'openai-codex' in set()``, the phone's symptom, while the three controls stay green; the
slot-identity test reddens too.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from agent_runtime.host_store import binding
from agent_runtime.host_store.fake import FakeHostSecureStore
from tests.agent_runtime.test_instance_conversation_owner import chat_head  # noqa: F401 (autouse)
from tests.agent_runtime.test_operator_session_inspection import inspect, target
from tests.agent_runtime.test_serve_rpc_open_chat import PERSONA, placed_agent, qa_persona  # noqa: F401

CODEX = "openai-codex"


@pytest.fixture(autouse=True)
def _unbound():
    binding.unbind_host_store()
    yield
    binding.unbind_host_store()


def _link(link: Path, real: Path) -> None:
    """``link`` -> ``real``, a directory link this OS lets a test make without privileges."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(real), str(link))
    else:
        os.symlink(real, link, target_is_directory=True)


@pytest.fixture
def phone_app(tmp_path, monkeypatch):
    """The phone's app folder: real at ``real/``, reached through ``app/`` (Android's two spellings)."""
    real = tmp_path / "real"
    (real / "hermes").mkdir(parents=True)
    linked = tmp_path / "app"
    _link(linked, real)
    return linked, real


def _phone_home(app: Path, monkeypatch) -> Path:
    from agent_runtime.bundle_profiles.manifest import apply_to_config, load_profile
    from hermes_cli import inventory
    from hermes_yaml import safe_dump

    home = app / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    monkeypatch.setattr(inventory, "_prewarm_pricing_async", lambda *args, **kwargs: None)
    (home / "config.yaml").write_text(safe_dump(apply_to_config(load_profile("bundled-phone"), {})),
                                      encoding="utf-8")
    return home


def _sign_in_codex_like_the_phone(monkeypatch) -> None:
    """``runtime.provider.signin.*``'s in-process runner (``auth.subprocess_signin: false``) over the
    Codex driver, with only the network step faked: the tokens land through ``_save_codex_tokens``
    exactly as ``provider_browser_login._codex`` saves them."""
    from agent_runtime.provider_signin import ProviderSignIns, run_login_in_process
    from hermes_cli import provider_browser_login
    from hermes_cli.auth_codex import _save_codex_tokens

    def driver(verify, flow, expiry=None):
        verify("https://auth.openai.example/codex/device", "PHON-CDX1")
        _save_codex_tokens({"access_token": "phone-codex-access", "refresh_token": "phone-codex-refresh"},
                           set_active=False)

    monkeypatch.setitem(provider_browser_login._DRIVERS, CODEX, driver)
    signins = ProviderSignIns(spawn=run_login_in_process)
    view = signins.begin(CODEX)
    deadline = time.monotonic() + 30
    while view["state"] not in {"succeeded", "failed", "cancelled", "expired"}:
        assert time.monotonic() < deadline, view
        time.sleep(.02)
        view = signins.poll(view["login_id"])
    assert view["state"] == "succeeded", view


def _offered_providers(placed_agent) -> set[str]:
    reply = inspect("models", target(placed_agent["persona_instance_id"]))
    assert "result" in reply, reply
    return {row["provider_id"] for row in reply["result"]["facts"]["models"]}


def _give_agent_its_own_profile(name: str = "neko") -> None:
    from agent_runtime.store import AgentStore
    from hermes_cli.profiles import create_profile

    create_profile(name)
    personas = AgentStore()
    persona = personas.get(PERSONA)
    persona.hermes_profile = name
    personas.save(persona)


@pytest.mark.parametrize("spelling", ["linked", "real"])
@pytest.mark.parametrize("own_profile", [True, False])
def test_a_codex_sign_in_on_the_phone_is_offered_in_the_agents_chat(
        placed_agent, phone_app, monkeypatch, spelling, own_profile):
    linked, real = phone_app
    app = linked if spelling == "linked" else real
    home = _phone_home(app, monkeypatch)
    store = FakeHostSecureStore()
    store.bind(profile="phone-a", store_root=app)
    if own_profile:
        _give_agent_its_own_profile()

    _sign_in_codex_like_the_phone(monkeypatch)

    # The sign-in is in the host store, and no plaintext auth.json was left in the app folder.
    assert list(store.slots) == ["hermes/v1/phone-a/hermes/auth.json"]
    assert not (home / "auth.json").exists()
    # The agent's chat is offered Codex — the phone read none when the agent had its own profile.
    assert CODEX in _offered_providers(placed_agent)


def test_one_file_reached_through_the_link_and_the_real_path_is_one_slot(phone_app):
    linked, real = phone_app
    bound = FakeHostSecureStore().bind(profile="phone-a", store_root=linked)
    spelled = linked / "hermes" / "auth.json"
    resolved = Path(os.path.realpath(spelled))
    assert resolved != spelled  # the link is real: two spellings of one file
    assert bound.slot(spelled) == bound.slot(resolved) == "hermes/v1/phone-a/hermes/auth.json"
    assert bound.contains(real / "hermes") and bound.contains(linked / "hermes")
    with pytest.raises(binding.OutsideStoreRoot):
        bound.slot(linked.parent / "elsewhere" / "auth.json")
