"""The argument groups more than one parser family shares.

Separate so a family adds the stage42 globals and the coordinator permission
flags by calling one function instead of repeating the flags.
"""

from __future__ import annotations


__layer__ = "wiring"
__all__ = [
    "_add_coordinator_permission_args",
    "_add_stage42_global_args",
]


def _add_stage42_global_args(
    parser,
    *,
    controls: frozenset[str] = frozenset(),
    omit: frozenset[str] = frozenset(),
) -> None:
    """The flags EVERY stage42 verb accepts.

    A flag registered here is a PROMISE made on every one of ~60 verbs at
    once, which is exactly why an unconsumed one is worse here than anywhere
    else: it is advertised in `--help` across the whole surface, accepted
    without complaint, and does nothing. An operator who reaches for it gets
    the unfiltered answer and no signal that the flag was ignored — the
    failure mode is a WRONG ANSWER believed, not an error seen.

    ``--filter`` and ``--watch`` were both that (removed 2026-07-28). Neither
    had a reader anywhere in the stack, and ``--filter`` was not merely
    unimplemented but undefined: no grammar, no documented contract, no
    consumer. Wiring it would have meant inventing one — and standing a
    generic untyped key=value filter beside the typed, domain-aware filters
    the list verbs already carry (``goal list --state/--workspace``,
    ``run list --state``, ``checkpoint --classes``), i.e. a SECOND filtering
    authority answering the same question, with the two free to disagree.
    There is also no honest shared place to apply it: the one point every
    list verb passes through, ``_print_stage42``, runs AFTER ``--limit`` has
    already truncated, so filtering there would filter the PAGE and call it
    the set. Removing the advertisement is the complete fix; the typed
    per-verb filters remain the real surface, and an unknown flag now fails
    loudly instead of being silently swallowed.

    ``--no-color`` is deliberately kept with no reader: nothing on this lane
    emits ANSI, so the flag's contract is already satisfied by construction.
    That is a no-op that tells the truth, not one that lies.

    `tests/hermes_cli/test_harness_cli.py::test_every_stage42_global_flag_is_honored`
    pins this — a new flag here must be read somewhere on the lane, or be
    declared satisfied-by-construction like ``--no-color``.

    ``controls`` is the opt-in half: a flag listed here is registered only on
    the verbs that ask for it. Only five tokens are ever asked for —
    ``dry_run`` (29 call sites), ``yes`` (7), ``sort`` (7),
    ``idempotency_key`` (3), ``limit`` (2), counted by walking the 58
    ``_add_stage42_global_args(...)`` calls in this file's AST. Branches for
    ``cursor`` and ``since`` also lived here and no call site had ever named
    either, so ``--cursor`` / ``--since`` could not be registered on any verb
    in the surface's history; they were removed 2026-08-19. (The neighbouring
    ``read --since-offset`` is a different, live flag.) A control token with no
    caller is the same defect as an unread flag, one level up: it advertises
    that a verb COULD opt in, and none can.

    ``omit`` names flags a verb genuinely does not implement, so they are never
    advertised on it. This is the SAME ruling that removed ``--filter`` and
    ``--watch`` from the whole surface, applied per-verb instead of globally:
    an accepted-but-ignored flag is a wrong answer believed. It defaults empty,
    so every existing call site is unchanged; a call site that passes it owes a
    comment saying what the verb cannot do. Use it sparingly — the point of this
    helper is a uniform surface, and a verb that omits half the contract should
    prompt the question of whether it belongs on this lane at all.
    """

    def add(*flags, **kwargs):
        if any(flag in omit for flag in flags):
            return
        if any(flag in parser._option_string_actions for flag in flags):  # noqa: SLF001 - argparse has no public query
            return
        parser.add_argument(*flags, **kwargs)

    add("-o", "--output", choices=["json", "table", "yaml", "wide"], default=None)
    add("--json", action="store_true", help="Alias for -o json")
    add("-q", "--quiet", action="store_true")
    add("--no-color", action="store_true")
    add("--fields", default=None)
    if "sort" in controls:
        add("--sort", default=None)
    if "limit" in controls:
        add("--limit", type=int, default=None)
    if "dry_run" in controls:
        add("--dry-run", action="store_true")
    if "yes" in controls:
        add("--yes", "-y", action="store_true")
    if "idempotency_key" in controls:
        add("--idempotency-key", default=None)


def _add_coordinator_permission_args(parser) -> None:
    parser.add_argument("--coordinator-id", default=None, help="Coordinator persona id when --requested-by is coordinator; coordinator:<id> carries it inline")
    parser.add_argument("--coordinator-max-spawns", type=int, default=None, help="In-scope create/spawn grant for this coordinator action")
    parser.add_argument("--coordinator-spawns-used", type=int, default=0, help="Create/spawn actions already used in this coordinator scope")
    parser.add_argument("--coordinator-may-kill-own", action="store_true", default=None, help="Allow killing instances spawned by this coordinator")
    parser.add_argument("--coordinator-no-kill-own", action="store_true", default=None, help="Require confirmation even for own-spawned instances")
    parser.add_argument("--coordinator-may-kill-others", action="store_true", default=None, help="Allow killing non-operator instances spawned by another coordinator")
