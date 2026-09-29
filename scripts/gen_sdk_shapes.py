"""Render ``agent/transports/sdk_shapes.py``: the typed fields of every provider-SDK model the loop reads.

The SDK-free clients (``agent/transports/httpx_client.py`` and its two wire modules) build
the SAME objects the ``openai`` / ``anthropic`` SDKs build — every field the SDK types is an
attribute (``None`` when the provider omitted it), nested models are records, and every key
the SDK does not type stays raw JSON — without importing either SDK. What "the fields the SDK
types" means is not written by hand: this script walks the SDKs' own pydantic models from the
roots the loop consumes and writes them down, and ``tests/agent/transports/
test_sdk_shapes_fresh.py`` re-renders in memory and diffs, so an SDK bump that adds a field
reds a test instead of silently diverging.

Run under the test environment (it has both SDKs)::

    python scripts/gen_sdk_shapes.py            # rewrite the module
    python scripts/gen_sdk_shapes.py --check    # exit 1 when the committed module is stale
"""

from __future__ import annotations

import argparse
import sys
import types
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "agent" / "transports" / "sdk_shapes.py"


def _roots() -> dict[str, object]:
    """Shape name -> SDK model class or discriminated union the loop receives at that name."""
    from anthropic.lib.streaming import _types as anthropic_stream
    from anthropic.types import ContentBlock, Message, RawMessageStreamEvent
    from anthropic.types.parsed_message import ParsedMessage
    from openai.types.chat import ChatCompletion, ChatCompletionChunk
    from openai.types.responses import Response, ResponseStreamEvent

    return {
        "chat.completion": ChatCompletion,
        "chat.completion.chunk": ChatCompletionChunk,
        "anthropic.message": Message,
        "anthropic.parsed_message": ParsedMessage,
        "anthropic.content_block": ContentBlock,
        "anthropic.raw_event": RawMessageStreamEvent,
        # ``MessageStream`` yields the raw events plus the SDK's derived ones.
        "anthropic.stream_event": anthropic_stream.ParsedMessageStreamEvent,
        "responses.response": Response,
        "responses.event": ResponseStreamEvent,
    }


def _strip(annotation):
    """Drop ``Annotated`` / ``Optional`` wrappers; returns ``(core, is_list)``."""
    while typing.get_origin(annotation) is typing.Annotated:
        annotation = typing.get_args(annotation)[0]
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        lists = [a for a in args if typing.get_origin(a) in (list, typing.List)]
        if lists and len(lists) == 1:
            return _strip(typing.get_args(lists[0])[0])[0], True
        if len(args) == 1:
            return _strip(args[0])
        return annotation, False
    if typing.get_origin(annotation) in (list, typing.List):
        return _strip(typing.get_args(annotation)[0])[0], True
    return annotation, False


def _models(annotation) -> list[type]:
    from pydantic import BaseModel

    while typing.get_origin(annotation) is typing.Annotated:
        annotation = typing.get_args(annotation)[0]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        out = []
        for arg in typing.get_args(annotation):
            if arg is type(None):
                continue
            inner = _models(arg)
            if not inner:
                return []  # a model mixed with a scalar: SDK keeps a non-object value as-is
            out += inner
        return out
    return []


def _tags(model: type) -> list[str]:
    field = model.model_fields.get("type")
    if field is None:
        return []
    core = field.annotation
    while typing.get_origin(core) is typing.Annotated:
        core = typing.get_args(core)[0]
    return [a for a in typing.get_args(core) if isinstance(a, str)] if typing.get_origin(core) is typing.Literal else []


class _Renderer:
    def __init__(self) -> None:
        self.kinds: dict[str, dict[str, object]] = {}
        self.unions: dict[str, dict[str, str]] = {}
        self._union_names: dict[frozenset, str] = {}
        self._kind_names: dict[type, str] = {}
        self.aliases: dict[str, dict[str, str]] = {}

    def _name(self, model: type) -> str:
        """``<sdk>.<Class>``; a second class of that name (the SDKs reuse ``Function``, ``Text``,
        ...) gets its defining module's last segment appended, so no two models share a row."""
        name = f"{model.__module__.split('.')[0]}.{model.__qualname__}".replace("[", "_").replace("]", "")
        if name in self._kind_names.values():
            name = f"{name}@{model.__module__.rsplit('.', 1)[-1]}"
        return name

    def kind(self, model: type) -> str:
        if model in self._kind_names:
            return self._kind_names[model]
        name = self._kind_names[model] = self._name(model)
        self.kinds[name] = {}
        fields = {}
        for field_name, info in model.model_fields.items():
            wire_name = info.alias or field_name
            fields[wire_name] = self.spec(info.annotation, f"{name}.{wire_name}")
            if wire_name != field_name:
                self.aliases.setdefault(name, {})[wire_name] = field_name
        self.kinds[name] = fields
        return name

    def union(self, models: list[type], where: str) -> str | None:
        """A discriminated union, named after the first field (or root) that declares it."""
        table = {}
        for model in models:
            tags = _tags(model)
            if not tags:
                return None
            for tag in tags:
                table.setdefault(tag, self.kind(model))
        name = self._union_names.setdefault(frozenset(table.items()), where)
        self.unions.setdefault(name, table)
        return name

    def target(self, annotation, where: str) -> str | None:
        models = _models(annotation)
        if len(models) == 1:
            return self.kind(models[0])
        if models:
            union = self.union(models, where)
            return None if union is None else "union:" + union
        return None

    def spec(self, annotation, where: str):
        core, is_list = _strip(annotation)
        target = self.target(core, where)
        return None if target is None else (target, "list" if is_list else "one")


def render() -> str:
    renderer = _Renderer()
    roots = {name: renderer.target(root, name) for name, root in _roots().items()}
    missing = [name for name, target in roots.items() if target is None]
    if missing:
        raise SystemExit(f"roots with no model: {missing}")
    import anthropic
    import openai

    lines = [
        '"""Typed fields of the provider-SDK models the loop reads — GENERATED, do not edit.',
        "",
        "Rendered by ``scripts/gen_sdk_shapes.py`` from openai "
        f"{openai.__version__} and anthropic {anthropic.__version__};",
        "``tests/agent/transports/test_sdk_shapes_fresh.py`` re-renders and diffs.",
        "",
        "``KINDS``: model -> field -> ``None`` (a scalar or an untyped value, kept as sent) or",
        "``(target, arity)`` where target is a model or ``union:<name>`` and arity ``one`` / ``list``.",
        "``UNIONS``: union -> discriminator (``type``) value -> model; an unknown value builds the FIRST",
        "model, as the SDKs' ``construct_type`` does. ``ALIASES``: model -> wire key -> attribute name.",
        "``ROOTS``: what each wire returns.",
        '"""',
        "",
        "# fmt: off",
        f"ROOTS = {roots!r}",
        "",
        "KINDS = {",
    ]
    for name in sorted(renderer.kinds):
        lines.append(f"    {name!r}: {renderer.kinds[name]!r},")
    lines += ["}", "", "UNIONS = {"]
    for name in sorted(renderer.unions):
        lines.append(f"    {name!r}: {renderer.unions[name]!r},")
    lines += ["}", "", f"ALIASES = {dict(sorted(renderer.aliases.items()))!r}", "# fmt: on", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"{TARGET.relative_to(ROOT)} is stale; run scripts/gen_sdk_shapes.py", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
