"""Render ``tui_gateway/contract_catalog_data.py``: the gateway's wire contracts as plain data.

The gateway's contracts (``tui_gateway/contracts/``) are pydantic models, and pydantic is
``pydantic-core`` (Rust), which a phone cannot load. Under ``tui_gateway.pydantic_contracts:
false`` the gateway reads the same catalog from this generated module instead
(``tui_gateway/contract_catalog.py``): every method, server request and event name, and for
every params / result model its SHAPE — the fields it declares (by wire name and, where the
model populates by name, by field name), which are required, which nest another model, a
list or map of one, or a union of several (with its discriminator), and whether unknown keys
are forbidden. Values' types are not recorded: the catalog answers "which keys", never "what
value" (the contract seam's docstring says why that is the phone's boundary).

It is rendered from the live pydantic models — upstream's catalog plus the fork's own
(``agent_runtime.conversations.worker_skills``) — so it cannot be a second source of truth:
``tests/tui_gateway/test_contract_catalog.py`` re-renders and diffs it, and measures the
pure validator against pydantic on every declared model.

    python scripts/gen_contract_catalog.py            # rewrite
    python scripts/gen_contract_catalog.py --check    # exit 1 when stale
"""

from __future__ import annotations

import argparse
import sys
import types
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TARGET = ROOT / "tui_gateway" / "contract_catalog_data.py"


def _registry():
    from agent_runtime.conversations.worker_skills import declare_contracts
    from tui_gateway.contracts import registry

    declare_contracts()
    return registry


def _unwrap(annotation):
    """``(core, arity, discriminator)``: Annotated / Optional stripped, list / dict noted."""
    discriminator = None
    while typing.get_origin(annotation) is typing.Annotated:
        args = typing.get_args(annotation)
        for meta in args[1:]:
            discriminator = getattr(meta, "discriminator", None) or discriminator
        annotation = args[0]
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        members = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(members) == 1:
            core, arity, inner = _unwrap(members[0])
            return core, arity, inner or discriminator
    if origin in (list, tuple, set, frozenset):
        return _unwrap(typing.get_args(annotation)[0])[0], "list", discriminator
    if origin is dict:
        return _unwrap(typing.get_args(annotation)[1])[0], "dict", discriminator
    return annotation, "one", discriminator


class _Renderer:
    def __init__(self) -> None:
        self.models: dict[str, dict] = {}
        self._names: dict[type, str] = {}

    def name(self, model: type) -> str:
        if model in self._names:
            return self._names[model]
        name = model.__qualname__.replace("<locals>.", "")
        if name in self._names.values():
            name = f"{model.__module__.rsplit('.', 1)[-1]}.{name}"
        self._names[model] = name
        self.models[name] = {}
        self.models[name] = self._shape(model)
        return name

    def _members(self, core) -> list[type]:
        from pydantic import BaseModel

        candidates = typing.get_args(core) if typing.get_origin(core) in (typing.Union, types.UnionType) else (core,)
        return [c for c in candidates if isinstance(c, type) and issubclass(c, BaseModel)]

    def _spec(self, info):
        core, arity, discriminator = _unwrap(info.annotation)
        discriminator = info.discriminator or discriminator
        members = self._members(core)
        if not members:
            return None
        is_union = typing.get_origin(core) in (typing.Union, types.UnionType)
        if len(members) == 1 and not is_union:
            return {"model": self.name(members[0]), "arity": arity}
        mapping = {}
        if isinstance(discriminator, str):
            for member in members:
                field = member.model_fields.get(discriminator)
                for tag in typing.get_args(field.annotation) if field is not None else ():
                    mapping[str(getattr(tag, "value", tag))] = self.name(member)
        return {"union": [self.name(m) for m in members], "tags": [m.__name__ for m in members], "arity": arity,
                "discriminator": discriminator if mapping else None, "mapping": mapping,
                # a non-model member (``RecordRepoItem | str``) accepts what no model member does
                "open": len(members) < len([a for a in typing.get_args(core) if a is not type(None)])}

    def _shape(self, model: type) -> dict:
        config = model.model_config
        by_name = bool(config.get("populate_by_name") or config.get("validate_by_name"))
        fields, names, required = {}, {}, []
        for field_name, info in model.model_fields.items():
            wire = info.validation_alias if isinstance(info.validation_alias, str) else info.alias or field_name
            fields[wire] = self._spec(info)
            names[wire] = wire
            if by_name and wire != field_name:
                names[field_name] = wire
            if info.is_required():
                required.append(wire)
        return {"extra": config.get("extra") or "ignore", "fields": fields, "names": names, "required": required}


def render() -> str:
    registry = _registry()
    renderer = _Renderer()
    # What the gateway validates at run time: method params, and a server request's params and
    # the answer to it. Results and payloads are OURS and are checked by the desktop suite only.
    methods = {name: renderer.name(c.params) for name, c in sorted(registry.METHODS.items())}
    requests = {name: [renderer.name(c.params), renderer.name(c.result)]
                for name, c in sorted(registry.SERVER_REQUESTS.items())}
    events = sorted(registry.EVENTS)
    lines = [
        '"""The gateway\'s wire contracts as plain data — GENERATED by scripts/gen_contract_catalog.py, do not edit.',
        "",
        "``METHODS``: name -> params model. ``SERVER_REQUESTS``: name -> [params model, result model].",
        "``EVENTS``: the event names. ``MODELS``: model -> {extra, fields: wire name -> spec, names: accepted key -> wire",
        "name, required}; a spec is None (a value), {model, arity} or {union: [models], tags: [class names],",
        "arity, discriminator, mapping: {tag: model}, open: a non-model member exists}; arity one/list/dict.",
        '"""',
        "",
        "# fmt: off",
        f"METHODS = {methods!r}",
        "",
        f"SERVER_REQUESTS = {requests!r}",
        "",
        f"EVENTS = {events!r}",
        "",
        "MODELS = {",
    ]
    for name in sorted(renderer.models):
        lines.append(f"    {name!r}: {renderer.models[name]!r},")
    lines += ["}", "# fmt: on", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"{TARGET.relative_to(ROOT)} is stale; run scripts/gen_contract_catalog.py", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
