"""The CLI verb runner a store-backed ``harness`` verb shares: run, print, or render the refusal.

D1.08. ``persona slots`` and ``workspace slots`` ran the same body — call the
store, print its object envelope, and turn a typed store refusal into
``emit_harness_error(..., code="invalid_payload", message="<reason>: <detail>")``.
Each caller names its refusal types; anything it does not name propagates.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hermes_cli.harness_support import _object_envelope, _print_stage42, emit_harness_error

__layer__ = "lanes"
__all__ = ["run_refusing_verb"]


def run_refusing_verb(
    args: Any,
    kind: str,
    action: Callable[[], dict[str, Any]],
    *,
    refusals: tuple[type[BaseException], ...],
    plain: tuple[type[BaseException], ...] = (),
    code: str = "invalid_payload",
) -> int:
    """Run ``action`` and print its ``kind`` envelope; exit 0.

    A ``refusals`` exception carries ``reason`` and ``detail`` and is rendered as
    ``"<reason>: <detail>"``; a ``plain`` one (an input-shape ``ValueError``, say)
    as its own text. Both exit with ``code``'s family. Any other exception is not
    this runner's to translate and propagates.
    """

    try:
        payload = action()
    except refusals as exc:
        return emit_harness_error(exc, args=args, code=code, message=f"{exc.reason}: {exc.detail}")
    except plain as exc:
        return emit_harness_error(exc, args=args, code=code, message=str(exc))
    _print_stage42(_object_envelope(kind, payload), args=args, default_output="json")
    return 0
