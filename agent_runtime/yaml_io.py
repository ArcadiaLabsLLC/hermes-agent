"""The fork's one YAML door, on ``ruamel.yaml`` — never ``pyyaml``.

Upstream's core dependencies carry only ``ruamel.yaml`` on Python 3.14, so the
pm-committed environment ``hermes update`` builds has no ``pyyaml``; a fork
module that imports ``yaml`` is unimportable there. Every fork module reads and
writes YAML through this facade instead (gate:
``tests/tooling/test_fork_modules_do_not_import_pyyaml.py``).

* ``dump`` IS upstream's emitter, ``hermes_yaml.safe_dump``, with the fork's
  defaults (insertion order, block style, readable Unicode). Its bytes are not
  pyyaml's — block sequences indent under their key, multi-line strings
  double-quote, ``y``/``n``/``1e3`` are quoted — so a realm artifact pyyaml
  wrote republishes once with the new bytes.
* ``load`` is NOT ``hermes_yaml.safe_load``, on purpose: upstream resolves a
  bare ``y``/``n`` to a boolean and ``1e3`` to a float, and every artifact this
  fork has published so far was written by pyyaml, which leaves all three
  unquoted because it reads them as strings. A flow-graph node's ``y:``
  coordinate would come back keyed ``True``. So ``load`` resolves scalars
  exactly as pyyaml did (YAML 1.1 minus those two rules) on ruamel's pure
  parser. Duplicate keys are rejected, as upstream rejects them. Everything
  ``dump`` writes reloads identically under either loader.

Round-trip (comment-preserving) editing is ``hermes_yaml.roundtrip_yaml``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import IO, Any

from hermes_yaml import YAMLError, safe_dump
from ruamel.yaml import YAML
from ruamel.yaml.resolver import VersionedResolver

__layer__ = "models"

__all__ = ["YAMLError", "dump", "dump_to", "load"]

_BOOL = "tag:yaml.org,2002:bool"
_FLOAT = "tag:yaml.org,2002:float"
# pyyaml's own YAML 1.1 rules (yaml/resolver.py); ruamel's 1.1 table differs in exactly these two.
_PYYAML_RULES: dict[str, re.Pattern[str]] = {
    _BOOL: re.compile(
        r"""^(?:yes|Yes|YES|no|No|NO
        |true|True|TRUE|false|False|FALSE
        |on|On|ON|off|Off|OFF)$""",
        re.X,
    ),
    _FLOAT: re.compile(
        r"""^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?
        |\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?
        |[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*
        |[-+]?\.(?:inf|Inf|INF)
        |\.(?:nan|NaN|NAN))$""",
        re.X,
    ),
}


class _PyyamlResolver(VersionedResolver):
    """YAML 1.1 scalar resolution as pyyaml performs it, with no ``%YAML`` directive."""

    @property
    def processing_version(self) -> tuple[int, int]:
        return (1, 1)

    def add_version_implicit_resolver(
        self, version: Any, tag: Any, regexp: Any, first: Any
    ) -> None:
        super().add_version_implicit_resolver(
            version, tag, _PYYAML_RULES.get(tag, regexp), first
        )


def load(text_or_stream: str | bytes | IO[str] | IO[bytes]) -> Any:
    """Safe-load one YAML document. Raises :class:`YAMLError` on malformed input."""

    document = (
        text_or_stream
        if isinstance(text_or_stream, (str, bytes))
        else text_or_stream.read()
    )
    parser = YAML(typ="safe", pure=True)
    parser.Resolver = _PyyamlResolver
    return parser.load(document)


def dump(
    data: Any,
    *,
    sort_keys: bool = False,
    default_flow_style: bool = False,
    allow_unicode: bool = True,
    width: int = 80,
) -> str:
    """Safe-dump ``data`` to a string (block style, keys in insertion order by default)."""

    return safe_dump(
        data,
        sort_keys=sort_keys,
        default_flow_style=default_flow_style,
        allow_unicode=allow_unicode,
        width=width,
    )


def dump_to(path: Path | str, data: Any, **kwargs: Any) -> None:
    """Write ``dump(data, **kwargs)`` to ``path`` as UTF-8 with LF line endings."""

    Path(path).write_bytes(dump(data, **kwargs).encode("utf-8"))
