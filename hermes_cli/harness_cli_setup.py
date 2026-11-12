"""The ``harness`` command's parser setup, importable without loading the ``eternia-harness`` plugin.

``plugins/eternia-harness/plugin.yaml`` names :func:`setup_harness_parser` on its ``harness`` row
(``setup:``), so ``hermes harness …`` builds its command line by importing this one function instead of
running the plugin's whole ``register(ctx)`` to learn the flags (``RT-HARNESS-PARSER-PLUGIN-LOAD-TWICE``).
The plugin registers the same function, so the parser is one whichever way it is attached.
"""

from __future__ import annotations

import time

__all__ = ["setup_harness_parser"]


def _record_harness_parser_ms(started: float) -> None:
    """The fork's boot-clock field (``harness_parser_ms``: harness import + tree build)."""
    try:
        from hermes_cli import _boot_clock
    except ImportError:  # stock upstream has no boot clock
        return
    _boot_clock.record_harness_parser_ms(int(max(0.0, time.monotonic() - started) * 1000))


def setup_harness_parser(parser) -> None:
    started = time.monotonic()
    try:
        from hermes_cli.harness import build_cli_parser

        build_cli_parser(parser)
    finally:
        _record_harness_parser_ms(started)
