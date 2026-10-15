"""Read-only executable identity, before attaching to a shared store owner."""
from __future__ import annotations

from agent_runtime.execution_identity import execution_identity

__layer__ = "wiring"


def add_execution_identity(subs) -> None:
    parser = subs.add_parser("execution-identity", help="Identify this Hermes installation without starting a service")
    parser.add_argument("--json", action="store_true", help="Print machine-readable identity")
    parser.set_defaults(func=print_execution_identity)


def print_execution_identity(args) -> int:
    from hermes_cli.harness_support import _print_stage42  # the envelope printer: ~290 modules, paid by this verb only

    value = execution_identity()
    _print_stage42({"id": value["execution_id"], **value}, args=args)
    return 0
