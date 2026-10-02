"""Both workspace spellings on every verb that takes a workspace (plan D8).

The harness parser had grown three unrelated conventions for the same argument:
``--workspace`` with dest ``workspace`` (office, board), ``--workspace`` with
dest ``workspace_id`` (``agent create``, an argv verb deleted 2026-10-02), and ``--workspace-id`` (persona
instance, mission chat). An operator who learned one verb's spelling was refused
by the next, and nothing in the tree said which was which — the spelling was a
per-verb accident, not a decision.

D8's answer is aliases: every verb accepts BOTH, nothing renamed, nothing
removed. This file is the fence that keeps it true for the NEXT verb somebody
adds, and it is a WALK of the real parser tree rather than a list, because a
typed list is a second copy of the roster that is free to fall behind the
parser it describes — which is the exact failure mode this repo has recorded
against hand-maintained membership lists elsewhere.

The discriminator is deliberately NOT the spelling. ``harness realm agents set``
has carried a ``--workspace`` flag since long before this rule, and it is a
``store_true`` switch with dest ``publish_workspace`` meaning "publish the
definitions the workspace rosters require" — a different argument that happens
to share four letters. A rule keyed on the option string would demand a
``--workspace-id`` alias for a boolean. So the rule is keyed on what the action
IS: an optional that binds one of the two workspace dests and consumes a value.
``test_the_discriminator_is_the_dest_not_the_spelling`` pins that carve-out.
"""

from __future__ import annotations

import argparse

import pytest

#: The two dests the harness spends on "which workspace", and the only two.
WORKSPACE_DESTS = frozenset({"workspace", "workspace_id"})

#: Both spellings, which every workspace-taking OPTION must offer.
BOTH_SPELLINGS = frozenset({"--workspace", "--workspace-id"})

#: A floor for the walk, not a roster. Its job is to fail a walk that stopped
#: descending (an ``add_parser`` refactor, a subparsers action this recursion
#: stops recognising) — a scan that matches nothing must never read as a pass.
#: The verbs D8 enumerates are 14; a walk finding fewer has lost part of the
#: tree, and one finding more is a NEW verb this rule already covered.
MINIMUM_WORKSPACE_VERBS = 14


def _root_parser() -> argparse.ArgumentParser:
    from hermes_cli.harness import build_parser

    parser = argparse.ArgumentParser(prog="hermes")
    build_parser(parser.add_subparsers(dest="root"))
    return parser


def _walk(parser: argparse.ArgumentParser, path: tuple[str, ...]):
    """Every (path, parser) in the real tree, aliases collapsed onto one path.

    ``choices`` maps every alias to the SAME parser object, so a naive iteration
    would report one verb once per spelling and make the failure messages lie
    about how many verbs are broken. The first key wins because ``add_parser``
    registers the canonical name before its aliases.
    """

    yield path, parser
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        seen: set[int] = set()
        for name, sub in action.choices.items():
            if id(sub) in seen:
                continue
            seen.add(id(sub))
            yield from _walk(sub, path + (name,))


def _workspace_options() -> dict[str, argparse.Action]:
    """Every subcommand that takes a workspace, keyed by its full verb path.

    An action qualifies when all three hold: it is an OPTIONAL (positionals such
    as ``harness workspace show <workspace_id>`` are not spelled with flags and
    have no alias question), it binds one of the two workspace dests, and it
    CONSUMES a value (``nargs == 0`` is a switch, never a workspace).
    """

    found: dict[str, argparse.Action] = {}
    for path, parser in _walk(_root_parser(), ()):
        for action in parser._actions:
            if not action.option_strings:
                continue
            if action.dest not in WORKSPACE_DESTS:
                continue
            if action.nargs == 0:
                continue
            found[" ".join(path)] = action
    return found


def test_the_walk_reaches_the_whole_tree():
    """Anti-vacuity, and the reason every other assertion here is worth reading.

    Every check below is a ``for`` over what the walk found, so a walk that
    found nothing passes them all. This is the guard that makes the empty set
    a failure instead of a clean run.
    """

    verbs = _workspace_options()

    assert len(verbs) >= MINIMUM_WORKSPACE_VERBS, sorted(verbs)
    # Spot the three conventions D8 unified, one verb from each, so a walk that
    # descended into only one subtree is caught by name rather than by count.
    for expected in (
        "harness level show",
        "harness office actor-upsert",
        "harness board create",
        "harness persona instance create",
        "harness mission-chat message",
    ):
        assert expected in verbs, sorted(verbs)


def test_every_workspace_verb_accepts_both_spellings():
    """The D8 rule itself.

    KILLING MUTATION: drop either spelling from any one ``add_argument`` above
    and this reds naming that verb — the assertion message carries the path, so
    the failure says WHICH verb regressed rather than that some verb did.
    """

    offenders = {
        path: sorted(action.option_strings)
        for path, action in _workspace_options().items()
        if not BOTH_SPELLINGS.issubset(set(action.option_strings))
    }

    assert offenders == {}, offenders


def test_the_two_spellings_land_on_the_same_dest():
    """An alias that wrote a second dest would satisfy the check above and still
    strand the verb: the handler reads ONE attribute. Parsing each verb twice —
    once per spelling — and comparing the parsed namespace is the runtime proof
    that the alias is an alias and not a new argument wearing the name.
    """

    parser = _root_parser()
    for path, action in _workspace_options().items():
        argv_base = path.split(" ")[1:]  # drop the "harness" root
        required = _required_extras(path)
        first = parser.parse_args(
            ["harness", *argv_base, *required, "--workspace", "ws_alias_probe"]
        )
        second = parser.parse_args(
            ["harness", *argv_base, *required, "--workspace-id", "ws_alias_probe"]
        )
        assert getattr(first, action.dest) == "ws_alias_probe", path
        assert getattr(second, action.dest) == "ws_alias_probe", path
        assert vars(first) == vars(second), path


def _required_extras(path: str) -> list[str]:
    """The OTHER required arguments each workspace verb needs to parse at all.

    Kept as a narrow table rather than derived, because deriving it would mean
    re-implementing argparse's requiredness rules; it is only ever read by the
    round-trip test above, and a verb missing from it fails loudly (argparse
    exits 2) rather than silently skipping.
    """

    return {
        "harness level set": ["--document", "{}"],
        "harness office actor-upsert": ["--actor-json", "{}"],
        "harness office actor-remove": ["--actor", "personainst_qa"],
        "harness office actor-restore": ["--actor", "personainst_qa"],
        "harness office resolve-conflict": [
            "--actor",
            "personainst_qa",
            "--take",
            "local",
        ],
        "harness office set-folders": ["--folders", "Agents"],
        "harness board card add": ["--title", "t"],
        "harness persona instance create": ["--persona", "qa", "--title", "t"],
        "harness persona instance open-chat": ["--persona", "qa"],
        "harness mission-chat message": ["--persona", "qa", "--message", "hi"],
    }.get(path, [])


def test_the_discriminator_is_the_dest_not_the_spelling():
    """``harness realm agents set --workspace`` is NOT a workspace argument.

    It is a ``store_true`` selector (dest ``publish_workspace``) choosing which
    persona definitions a realm publishes. A rule keyed on the option STRING
    would demand a ``--workspace-id`` alias for a boolean switch and, worse,
    would read as satisfied the day somebody added one. This pins that the walk
    excludes it for the two structural reasons it should: the dest and the
    zero-width value.
    """

    parser = _root_parser()
    realm_agents_set = None
    for path, sub in _walk(parser, ()):
        if path == ("harness", "realm", "agents", "set"):
            realm_agents_set = sub
    assert realm_agents_set is not None

    switch = next(
        action
        for action in realm_agents_set._actions
        if "--workspace" in action.option_strings
    )
    assert switch.dest == "publish_workspace"
    assert switch.nargs == 0
    assert "harness realm agents set" not in _workspace_options()


@pytest.mark.parametrize(
    "argv",
    [
        ["harness", "office", "show", "--workspace-id", "ws"],
        ["harness", "persona", "instance", "create", "--persona", "qa", "--title", "t", "--workspace", "ws"],
        ["harness", "mission-chat", "message", "--persona", "qa", "--message", "hi", "--workspace", "ws"],
    ],
)
def test_the_previously_refused_spelling_now_parses(argv):
    """The operator-facing half, one verb per old convention.

    Every verb here parses exactly as written.
    """

    parser = _root_parser()
    args = parser.parse_args(argv)
    # BOTH operands compared. Written as `A or B == "ws"` this parsed as
    # `A or (B == "ws")`, so any truthy `workspace_id` — including one the alias
    # had written to the WRONG dest — satisfied it without ever reaching the
    # comparison. The bug and its fix are one line apart and the difference is
    # a pair of parentheses argparse would never have told anyone about.
    assert "ws" in {
        getattr(args, "workspace_id", None),
        getattr(args, "workspace", None),
    }, vars(args)
