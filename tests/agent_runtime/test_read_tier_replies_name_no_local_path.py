"""Every verb a view-only device may call answers it with no absolute local path in a path field.

Row ``RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-ITS-AGENTS-CONTEXT-FILES`` (review w1122d.12) landed this
census over ``registry.computer_reach()``, the verbs a computer at Look or Run chats reached. Row
``RT-ACCOUNT-ONLY-A-PHONE-ANSWERS-A-PAIRED-COMPUTER-ONLY-AS-ONE-OF-YOUR-OWN`` (review w1122d.15) retired those levels
and KEPT the path projection ("below console tier"), because it also protects a view-only device (``gateway pair
--tier read``, the QA mint's default): the census now walks the verbs such a device reaches, every ``read``-tier
verb outside ``LOCAL_CONSOLE_METHODS``. Each is either CALLED through the real dispatcher as a read-tier device
on a placed agent whose profile holds a ``SOUL.md``, or EXCUSED with the reason it is not read here. A verb that
becomes reachable and is in neither table reddens the census until it is classified. A called verb must answer a
``result``, so the census reads a real reply, not a refusal. A leak the census found that is not this row's
one-line pass-through is filed, and its verb sits in ``_FILED`` (exact) until that row lands.

Killing mutations (each red seen 2026-11-23, in a scratch tree, on the read-tier census):

* ``console_operations.prompt_observability_agent``: return the result unprojected, and the census finds the
  SOUL.md path under ``context_files[].path`` in ``runtime.prompt_observability.agent``'s reply;
* ``health._runtime_health``: return ``runtime_health()`` unprojected, and the census finds ``interpreter``,
  ``runtime_root`` and ``hermes_home`` in ``runtime.health``'s reply;
* drop ``runtime.health`` from ``_CALLED``, and the coverage test names it;
* drop ``runtime.characters.list`` from ``_FILED``, and the census names its ``home`` paths.

Earlier reds on the computer census (2026-11-23, rows w1122d.12 and .13) are in those rows' commits; the
``interpreter`` key in ``_PATH_KEYS`` is load-bearing (a path key with no path suffix).
"""

from __future__ import annotations

import re

import pytest

from agent_runtime import call_authorization as ca
from agent_runtime import serve_rpc
from agent_runtime.serve_rpc import registry
from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # noqa: F401  (fixtures)

#: An absolute path as a whole value: POSIX, home-relative, a Windows drive or a UNC share.
_ABSOLUTE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\]|\\\\)")
#: A key that names where something lives on disk.
_PATH_KEYS = frozenset({"path", "workdir", "cwd", "runtime_root", "repo_scope", "hermes_home", "home", "interpreter"})
_PATH_SUFFIXES = ("_path", "_dir", "_root", "_home")


def _instance(agent):
    return {"instance_id": agent["persona_instance_id"]}


def _persona_instance(agent):
    return {"persona_instance_id": agent["persona_instance_id"]}


def _no_params(agent):
    return {}


def _persona(agent):
    return {"persona_id": agent["persona_id"]}


#: Each verb read here, with the params it is called with on the placed agent.
_CALLED = {
    "peer.ping": _no_params,
    "runtime.admission.status": _no_params,
    "runtime.character.assignment.get": lambda agent: {"kind": "persona", "id": agent["persona_id"], **_persona(agent)},
    "runtime.characters.list": _no_params,
    "runtime.events.after": _no_params,
    "runtime.health": _no_params,
    "runtime.messaging.status": _no_params,
    "runtime.office.get": lambda agent: {"workspace_id": agent["workspace_id"]},
    "runtime.persona.instance.detail": _instance,
    "runtime.pets.gallery": _no_params,
    "runtime.prompt_observability.agent": _instance,
    "runtime.provider.list": _no_params,
    "runtime.speech.status": _no_params,
}

#: Each verb not read here, and why. A binary reply carries bytes and a media type, no path field; a read that
#: needs a minted handle, a draft, a live subscription or a service a test does not run has its own verb test.
_EXCUSED = {
    "peer.roster.list": "answers a paired INSTALL only; a device is refused in the handler",
    "runtime.character.assignment.preview_migration": "takes the legacy-assignment lock; get reads the same record",
    "runtime.character.portrait": "a binary portrait",
    "runtime.characters.cells": "needs a sprite draft",
    "runtime.characters.sprite": "needs an installed character's sheet",
    "runtime.characters.status": "needs a sprite draft",
    "runtime.characters.thumb": "a binary thumbnail of a sprite draft",
    "runtime.discussion.capabilities": "needs the discussion service, absent in a test",
    "runtime.discussion.preset.get": "needs the discussion service, absent in a test",
    "runtime.discussion.preset.list": "needs the discussion service, absent in a test",
    "runtime.discussion.roster": "needs the discussion service, absent in a test",
    "runtime.discussion.run.active": "needs the discussion service, absent in a test",
    "runtime.discussion.run.get": "needs the discussion service, absent in a test",
    "runtime.discussion.run.list": "needs the discussion service, absent in a test",
    "runtime.discussion.table.get": "needs the discussion service, absent in a test",
    "runtime.discussion.table.list": "needs the discussion service, absent in a test",
    "runtime.discussion.workspaces": "needs the discussion service, absent in a test",
    "runtime.gateway.reverse.offer": "a device's one-shot offer; its receipt is held: true",
    "runtime.gateway.reverse.withdraw": "a device's one-shot withdraw; its receipt is two booleans",
    "runtime.local_llama.setup.capabilities": "needs the owning local-llama manager, absent in a test",
    "runtime.local_llama.status": "needs the owning local-llama manager, absent in a test",
    "runtime.office.subscribe": "opens a live subscription; office.get reads the same frame",
    "runtime.office.unsubscribe": "closes a live subscription",
    "runtime.persona.prewarm": "fills visibility memos; its receipt is counts",
    "runtime.pets.sprite": "needs an installed pet's sheet",
    "runtime.pets.thumb": "a binary thumbnail",
    "runtime.profiles.avatar": "a binary avatar",
    "runtime.provider.models": "the models.dev entries of named catalogs: model facts, no file",
    "runtime.provider.usage": "asks a provider for its rate windows over the network",
    "runtime.skills.catalog": "needs a prompt-context frame's skills hash",
}


#: Each called verb the census found handing a view-only device a local path, with the row that fixes it.
#: Exact, not a ceiling: a verb fixed (or a new leak) reddens the census until this table says so.
_FILED: dict[str, str] = {
    "runtime.characters.list": "RT-FU-A-VIEW-ONLY-DEVICE-IS-SENT-WHERE-THIS-COMPUTER-KEEPS-ITS-CHARACTERS",
}


@pytest.fixture
def census_agent(placed_agent):
    """The placed agent, its profile holding a SOUL.md and a config file, so a path has every chance to land."""

    from agent_runtime.store import AgentStore
    from hermes_cli.profiles import get_profile_dir

    profile = get_profile_dir("census")
    profile.mkdir(parents=True, exist_ok=True)
    personas = AgentStore()
    persona = personas.get(placed_agent["persona_id"])
    persona.hermes_profile = "census"
    personas.save(persona)
    (profile / "SOUL.md").write_text("Census soul.\n", encoding="utf-8")
    (profile / "config.yaml").write_text("toolsets:\n  - web\n  - no-such-toolset\n", encoding="utf-8")
    from agent_runtime import paths
    from agent_runtime.gateway_identity import ensure_install_identity
    from agent_runtime.parse_cache import clear_parse_cache
    clear_parse_cache()
    return {**placed_agent, "workspace_id": placed_agent.get("workspace_id") or "ws_open_chat_test",
            "install_id": ensure_install_identity(paths.store_root()).install_id}


def _view_only_device() -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_DEVICE, transport=ca.TRANSPORT_GATEWAY, connection_key="dev-census",
                        device_id="dev_census", device_tier=ca.TIER_READ, device_kind=ca.DEVICE_KIND_DEVICE)


def _read_tier_verbs() -> set[str]:
    """Every verb a view-only device passes the gate to: ``read`` tier, outside ``LOCAL_CONSOLE_METHODS``."""

    registry.ensure_lazy_families()
    return {name for name, tier in registry.method_tiers().items()
            if tier == ca.TIER_READ and name not in ca.LOCAL_CONSOLE_METHODS}


def _path_fields(node, where=""):
    """Every ``(where, value)`` whose key names a path and whose value is an absolute local path."""

    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{where}.{key}"
            if (key in _PATH_KEYS or key.endswith(_PATH_SUFFIXES)) and isinstance(value, str) and _ABSOLUTE.match(value):
                yield here, value
            yield from _path_fields(value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _path_fields(value, f"{where}[{index}]")


def test_every_verb_a_view_only_device_reaches_is_read_or_excused():
    reach = _read_tier_verbs()
    assert not set(_CALLED) & set(_EXCUSED)
    assert set(_CALLED) | set(_EXCUSED) == reach, {
        "unclassified": sorted(reach - set(_CALLED) - set(_EXCUSED)),
        "no longer reached": sorted((set(_CALLED) | set(_EXCUSED)) - reach)}


def test_no_called_verb_hands_a_view_only_device_a_local_path(census_agent):
    refused, found = {}, {}
    for name, params in sorted(_CALLED.items()):
        reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": name, "method": name, "params": params(census_agent)},
                                         serve_rpc.RpcContext(caller=_view_only_device(),
                                                              transport=ca.TRANSPORT_GATEWAY))
        if "result" not in reply:
            refused[name] = reply.get("error")
            continue
        leaks = list(_path_fields(reply["result"]))
        if leaks:
            found[name] = leaks
    assert not refused, refused  # the census reads real replies, not refusals
    assert set(found) == set(_FILED), {name: leaks for name, leaks in found.items() if name not in _FILED} or {
        "fixed, drop from _FILED": sorted(set(_FILED) - set(found))}
