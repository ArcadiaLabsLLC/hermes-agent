"""``hermes namespace …`` — fork-owned; dispatched by ``main.py`` before argparse, like ``pm``.

Plan: ``EterniaLauncher/docs/embedded_hermes/planned/ONE_HERMES_INSTALL_PROFILE_NAMESPACE_2026-10-19.md``
§2.7, §4 H1/H3. Every verb prints ONE JSON object on stdout. Exit 0: done (``probe`` always exits 0
when it ran — a refusal of the asked id rides its ``refusal`` field); exit 2: a typed refusal (one
``{"ok": false, "error": "namespace_refused", "reason": …}`` object) or an unknown verb.

* ``probe [<id>]`` — the launcher's pre-spawn capability check (an older Hermes exits non-zero on
  the unknown subcommand, so "exit 0 + JSON" is the capability). Reads only; writes nothing.
* ``list`` — every namespace: id, kind (``account`` for ``acct-<16 hex>``, else ``profile``), size,
  last serve, busy, created / seeded-from.
* ``seed <id> --from <base|ns-id> [--dry-run]`` — once, at creation (owner ruling Q11); the result
  lists what was copied, what was skipped (each with a reason) and what the namespace borrows.
  ``--dry-run`` prints that plan, refuses as the real seed would, and writes nothing.
* ``reset <id>`` / ``delete <id>`` — refused while a serve holds the namespace, for ``base`` and for
  this process's own namespace.
* ``import-sessions <id> <export.jsonl> [--bind SRC=DST …] [--dry-run]`` — Hermes' own
  ``sessions export`` into a named namespace, each chat rebound to one of its persona instances
  (``agent_runtime/own_session_import.py``, row RT-SESSIONS-IMPORT-OWN-EXPORT); never ``base``.

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


def _session_import():
    from agent_runtime import own_session_import  # RT-SESSIONS-IMPORT-OWN-EXPORT

    return own_session_import


def _admin():
    from agent_runtime import namespace_admin  # the runtime half; probe stays stdlib-fast

    return namespace_admin


#: verb -> its runner (argparse's ``set_defaults(run=…)``: a table, not a ladder).
_RUNNERS = {
    "probe": lambda args: ns.probe(os.environ, args.id),
    "list": lambda args: _admin().list_namespaces(os.environ),
    "seed": lambda args: _admin().seed(args.id, args.source, os.environ, dry_run=args.dry_run,
                                       with_memories=args.with_memories),
    "reset": lambda args: _admin().reset(args.id, os.environ),
    "delete": lambda args: _admin().delete(args.id, os.environ),
    "import-sessions": lambda args: _session_import().run_namespace_verb(args, os.environ),
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
    seed.add_argument("--dry-run", action="store_true",
                      help="print the plan (copied / skipped with reason / borrowed) and write nothing")
    seed.add_argument("--with-memories", action="store_true",
                      help="also copy each home's memories/ (the owner's own reseed; acct- namespaces only)")
    imports = verbs.add_parser("import-sessions",
                               help="import a `hermes sessions export` JSONL into a namespace, rebinding each chat")
    imports.add_argument("id")
    imports.add_argument("path", help="the export file (read only, never written)")
    imports.add_argument("--bind", action="append", metavar="SRC=DST",
                         help="bind chats of source instance (or persona) SRC to the namespace's instance DST")
    imports.add_argument("--dry-run", action="store_true", help="report what would import and skip; write nothing")
    for verb in ("reset", "delete"):
        verbs.add_parser(verb, help=f"{verb} a namespace (refused while a serve holds it)").add_argument("id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _namespace_parser().parse_args(list(sys.argv[2:] if argv is None else argv))
    try:
        payload = _RUNNERS[args.verb](args)
    except ns.NamespaceRefused as exc:
        payload = exc.payload()
    _emit(payload)
    return 2 if payload.get("ok") is False else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
