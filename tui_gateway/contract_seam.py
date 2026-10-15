"""Which contract registry the gateway reads: pydantic's, or the generated catalog (phone profile).

The gateway validates its wire against the pydantic models in ``tui_gateway/contracts/``
(``registry.validate_params`` answers ``4000`` for an unknown key; results and payloads are
checked and logged). pydantic is ``pydantic-core`` (Rust), which a phone cannot load, and the
phone runs this same gateway in-process (``agent_runtime.conversations.in_process_peer``). So
every runtime reader of the registry reads it through :data:`registry` here, and the profile
switch ``tui_gateway.pydantic_contracts`` (default on) picks the implementation:

* on (desktop) — ``tui_gateway.contracts.registry``, unchanged;
* off (phone) — :mod:`tui_gateway.contract_catalog`: the same catalog rendered from those
  models to plain data, with a pure-Python SHAPE validator (unknown keys, missing required
  keys, nested models and unions — never value types).

Why shape and not types is the phone's boundary: the check the gateway performs on params is
the unknown-key one (a client and a backend of different versions), which the shape answers
exactly (measured against pydantic in ``tests/tui_gateway/test_contract_catalog.py``); the
result / payload checks only log in production and gate the desktop suite, where the models
are; and the phone's one client ships in the same binary as this gateway, generated from the
same models (``apps/shared/src/gateway-contract.generated.ts``), so a value of the wrong type
has no version to come from.
"""

from __future__ import annotations

from types import ModuleType

__all__ = ["contract_registry", "pydantic_contracts_enabled", "registry"]


def pydantic_contracts_enabled() -> bool:
    """``tui_gateway.pydantic_contracts`` — off in a profile that ships no pydantic."""
    from hermes_cli.config_switches import config_switch

    return config_switch("tui_gateway", "pydantic_contracts", default=True)


def contract_registry() -> ModuleType:
    """The registry module the profile switch selects (see the module docstring)."""
    if pydantic_contracts_enabled():
        from tui_gateway.contracts import registry as pydantic_registry

        return pydantic_registry
    from tui_gateway import contract_catalog

    return contract_catalog


class _Registry:
    """``tui_gateway.contracts.registry``'s attributes, resolved through the switch on each read."""

    __slots__ = ()

    def __getattr__(self, name: str):
        return getattr(contract_registry(), name)

    def __repr__(self) -> str:
        return "<gateway contract registry (tui_gateway.pydantic_contracts)>"


registry = _Registry()
