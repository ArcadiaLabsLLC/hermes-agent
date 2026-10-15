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
* ``load`` IS upstream's reader, ``hermes_yaml.safe_load`` (YAML 1.1: a bare
  ``y``/``n`` is a boolean, ``1e3`` a float, duplicate keys are rejected). It
  used to carry a private pyyaml-compatible resolver for artifacts pyyaml had
  written with those scalars unquoted; the 2026-09-30 sweep (lane h14-yaml)
  found none left in any store, realm checkout or the tree, so it is gone.

Round-trip (comment-preserving) editing is ``hermes_yaml.roundtrip_yaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO, Any

from hermes_yaml import YAMLError, safe_dump, safe_load

__layer__ = "models"

__all__ = ["YAMLError", "dump", "dump_to", "load"]

#: Safe-load one YAML document; raises :class:`YAMLError` on malformed input.
load = safe_load


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
