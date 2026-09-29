"""``tui_gateway.contracts.registry`` without pydantic: the generated catalog and a shape validator.

Selected by :mod:`tui_gateway.contract_seam` under ``tui_gateway.pydantic_contracts: false``
(the phone profile). The tables and the names read at run time are the registry's own —
``METHODS`` / ``SERVER_REQUESTS`` / ``EVENTS`` of contracts carrying ``params`` / ``result``
/ ``payload`` models, a model's ``model_fields`` and ``model_validate``, and
``validate_params`` / ``check_params_accepted`` / ``check_result`` / ``check_payload`` — over
``tui_gateway/contract_catalog_data.py``, which ``scripts/gen_contract_catalog.py`` renders
from the pydantic models themselves.

The validator checks SHAPE: unknown keys where the model forbids them, required keys, and
the same for every nested model, list, map and union member (a smart union passes when any
member does; a discriminated one picks its member by tag). It reports them with pydantic's
error ``type`` / ``loc`` / ``msg``, so ``validate_params`` answers the unknown-key ``4000``
exactly as the pydantic registry does. Value types are not checked (the seam's docstring
says why), and the result / payload checks — which only log in production — do nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tui_gateway import contract_catalog_data as _data

__all__ = [
    "EVENTS", "METHODS", "SERVER_REQUESTS", "ContractShape", "ShapeError", "check_params_accepted",
    "check_payload", "check_result", "shape_errors", "validate_params",
]

_EXTRA = "Extra inputs are not permitted"
_MISSING = "Field required"


class ShapeError(ValueError):
    """``pydantic.ValidationError``'s surface: ``errors()`` lists ``{type, loc, msg}``."""

    def __init__(self, title: str, errors: list[dict]) -> None:
        self._errors = errors
        super().__init__(f"{len(errors)} validation error(s) for {title}: "
                         + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in errors))

    def errors(self) -> list[dict]:
        return list(self._errors)


class ContractShape:
    """A contract model as the registry's readers use one: ``model_fields`` and ``model_validate``."""

    def __init__(self, name: str) -> None:
        self.__name__ = name
        self.model_fields = dict.fromkeys(_data.MODELS[name]["names"])

    def model_validate(self, value: Any) -> Any:
        errors = shape_errors(self.__name__, value)
        if errors:
            raise ShapeError(self.__name__, errors)
        return value


@dataclass(frozen=True)
class MethodContract:
    """A method or server request. A method's ``result`` is ``None``: results are ours, checked by
    the desktop suite against the models, and the catalog does not carry their shapes."""

    name: str
    params: ContractShape
    result: ContractShape | None = None
    doc: str = ""


@dataclass(frozen=True)
class EventContract:
    """An event name; its payload is ours (see :class:`MethodContract`), so none is carried."""

    name: str
    payload: None = None
    doc: str = ""


METHODS = {name: MethodContract(name, ContractShape(params)) for name, params in _data.METHODS.items()}
SERVER_REQUESTS = {name: MethodContract(name, ContractShape(params), ContractShape(result))
                   for name, (params, result) in _data.SERVER_REQUESTS.items()}
EVENTS = {name: EventContract(name) for name in _data.EVENTS}


# ── the shape walk ───────────────────────────────────────────────────────────


def shape_errors(model: str, value: Any, loc: tuple = ()) -> list[dict]:
    """pydantic's errors for ``value`` as ``model``, restricted to shape, in pydantic's order:
    the declared fields in order (a nested model's errors where its field is), then unknown keys."""
    if not isinstance(value, dict):
        return [{"type": "model_type", "loc": loc, "msg": f"Input should be a valid dictionary or instance of {model}"}]
    shape = _data.MODELS[model]
    names = shape["names"]
    given = {names[key]: key for key in value if key in names}
    errors: list[dict] = []
    for wire, spec in shape["fields"].items():
        key = given.get(wire)
        if key is None:
            if wire in shape["required"]:
                errors.append({"type": "missing", "loc": (*loc, wire), "msg": _MISSING})
        elif spec is not None:
            errors += _value_errors(spec, value[key], (*loc, key))
    if shape["extra"] == "forbid":
        errors += [{"type": "extra_forbidden", "loc": (*loc, key), "msg": _EXTRA} for key in value if key not in names]
    return errors


def _value_errors(spec: dict, value: Any, loc: tuple) -> list[dict]:
    if value is None:
        return []
    arity = spec["arity"]
    if arity == "list":
        return [e for i, item in enumerate(value) for e in _one(spec, item, (*loc, i))] if isinstance(value, list) else []
    if arity == "dict":
        return [e for key, item in value.items() for e in _one(spec, item, (*loc, key))] if isinstance(value, dict) else []
    return _one(spec, value, loc)


def _one(spec: dict, value: Any, loc: tuple) -> list[dict]:
    if "model" in spec:
        return shape_errors(spec["model"], value, loc)
    if not isinstance(value, dict):
        # A non-object is a value-type question; an open union's scalar member may take it.
        return [] if spec["open"] else [{"type": "model_type", "loc": loc, "msg": "Input should be an object"}]
    if spec["discriminator"] is not None:
        tag = value.get(spec["discriminator"])
        member = spec["mapping"].get(str(tag)) if tag is not None else None
        if member is None:
            return [{"type": "union_tag_invalid", "loc": loc, "msg": f"Input tag {tag!r} does not match any tag"}]
        return shape_errors(member, value, (*loc, str(tag)))
    attempts = [shape_errors(member, value, (*loc, tag)) for member, tag in zip(spec["union"], spec["tags"])]
    if any(not errors for errors in attempts):
        return []  # smart mode: the first member that validates wins, and reports nothing
    return [e for errors in attempts for e in errors]


# ── the registry's runtime checks ────────────────────────────────────────────


def validate_params(contract: MethodContract, params: dict) -> tuple[dict | None, str | None]:
    """The registry's unknown-key ``4000`` — the one params check the gateway performs."""
    for err in shape_errors(contract.params.__name__, params):
        if err["type"] == "extra_forbidden":
            loc = ".".join(str(p) for p in err["loc"]) or "params"
            return None, (f"invalid params for {contract.name}: {loc}: {err['msg']} — the client and "
                          "the Hermes backend are out of sync (different versions); run `hermes update` "
                          "and restart both")
    return params, None


def check_params_accepted(contract: MethodContract, params: dict) -> None:
    """Logs only, in production; the desktop suite runs it against the models."""


def check_result(contract: MethodContract, result: dict) -> None:
    """Logs only, in production; the desktop suite runs it against the models."""


def check_payload(name: str, payload: dict | None) -> None:
    """Logs only, in production; the desktop suite runs it against the models."""
