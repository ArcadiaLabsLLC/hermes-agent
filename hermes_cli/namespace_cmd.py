"""``hermes namespace …`` — fork-owned; dispatched by ``main.py`` before argparse, like ``pm``.

Plan: ``EterniaLauncher/docs/embedded_hermes/planned/ONE_HERMES_INSTALL_PROFILE_NAMESPACE_2026-10-19.md``
§2.7, §4 H1/H3. Every verb prints ONE JSON object on stdout. Exit 0: done (``probe`` always exits 0
when it ran — a refusal of the asked id rides its ``refusal`` field); exit 2: a typed refusal (one
``{"ok": false, "error": "namespace_refused", "reason": …}`` object) or an unknown verb.

* ``probe [<id>]`` — the launcher's pre-spawn capability check (an older Hermes exits non-zero on
  the unknown subcommand, so "exit 0 + JSON" is the capability). Reads only; writes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from hermes_cli import _namespace_bootstrap as ns


def _emit(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes namespace", description="Hermes data namespaces.")
    verbs = parser.add_subparsers(dest="verb", required=True)
    probe = verbs.add_parser("probe", help="capability check: exit 0 + JSON (namespaces dir, root, budget)")
    probe.add_argument("id", nargs="?", default=None)
    return parser


def _run(args: argparse.Namespace) -> object:
    if args.verb == "probe":
        return ns.probe(os.environ, args.id)
    raise AssertionError(args.verb)  # argparse admits only the verbs above


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(sys.argv[2:] if argv is None else argv))
    try:
        _emit(_run(args))
    except ns.NamespaceRefused as exc:
        _emit(exc.payload())
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
