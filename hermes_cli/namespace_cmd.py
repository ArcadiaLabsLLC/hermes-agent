"""``hermes namespace …`` — fork-owned; dispatched by ``main.py`` before argparse, like ``pm``.

Plan: ``EterniaLauncher/docs/embedded_hermes/planned/ONE_HERMES_INSTALL_PROFILE_NAMESPACE_2026-10-19.md``
§2.7, §4 H1/H3. Every verb prints ONE JSON object on stdout. Exit 0: done (``probe`` always exits 0
when it ran — a refusal of the asked id rides its ``refusal`` field); exit 2: a typed refusal (one
``{"ok": false, "error": "namespace_refused", "reason": …}`` object) or an unknown verb.

* ``probe [<id>]`` — the launcher's pre-spawn capability check (an older Hermes exits non-zero on
  the unknown subcommand, so "exit 0 + JSON" is the capability). Reads only; writes nothing.
* ``list`` — every namespace: id, kind (``account`` for ``acct-<16 hex>``, else ``profile``), size,
  last serve, busy, created / seeded-from.
* ``seed <id> --from <base|ns-id>`` — once, at creation (owner ruling Q11).
* ``reset <id>`` / ``delete <id>`` — refused while a serve holds the namespace, for ``base`` and for
  this process's own namespace.

The verbs live in ``agent_runtime/namespace_admin.py``; they are not gated by the external-access
rule (they name every namespace explicitly and run no agent in one).
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


def _admin():
    from agent_runtime import namespace_admin  # the runtime half; probe stays stdlib-fast

    return namespace_admin


#: verb -> its runner (argparse's ``set_defaults(run=…)``: a table, not a ladder).
_RUNNERS = {
    "probe": lambda args: ns.probe(os.environ, args.id),
    "list": lambda args: _admin().list_namespaces(os.environ),
    "seed": lambda args: _admin().seed(args.id, args.source, os.environ),
    "reset": lambda args: _admin().reset(args.id, os.environ),
    "delete": lambda args: _admin().delete(args.id, os.environ),
}


def _namespace_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes namespace", description="Hermes data namespaces.")
    verbs = parser.add_subparsers(dest="verb", required=True)
    probe = verbs.add_parser("probe", help="capability check: exit 0 + JSON (namespaces dir, root, budget)")
    probe.add_argument("id", nargs="?", default=None)
    verbs.add_parser("list", help="every namespace of this install")
    seed = verbs.add_parser("seed", help="copy the seed allowlist into a NEW namespace, once")
    seed.add_argument("id")
    seed.add_argument("--from", dest="source", required=True, help="'base' or a namespace id, named explicitly")
    for verb in ("reset", "delete"):
        verbs.add_parser(verb, help=f"{verb} a namespace (refused while a serve holds it)").add_argument("id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _namespace_parser().parse_args(list(sys.argv[2:] if argv is None else argv))
    try:
        _emit(_RUNNERS[args.verb](args))
    except ns.NamespaceRefused as exc:
        _emit(exc.payload())
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
