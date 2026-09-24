"""Fork-owned tests moved out of ``tests/hermes_cli/test_dashboard_tui_backcompat.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import pytest

from tests.hermes_cli.test_dashboard_tui_backcompat import (  # noqa: F401 — upstream names the moved tests use
    OLD_APP_SHELL_ARGV,
    REPO_ROOT,
    _cli_parser,
)


def test_the_tui_flag_is_accepted_and_ignored_not_acted_on():
    """Accepted is only half the contract — the rest of the argv must survive.

    A shim that swallowed the flag by consuming the argv after it would parse
    just as cleanly and still brick the old app shell, which passes ``--host`` /
    ``--port`` AFTER ``--tui``.
    """
    args = _cli_parser().parse_args(OLD_APP_SHELL_ARGV)

    assert args.host == "127.0.0.1"
    assert args.port == 39997
    assert args.no_open is True


def test_a_genuinely_unknown_flag_still_errors():
    """ANTI-VACUITY: this is the real parser, and it still rejects real typos.

    Without this, a parser that accepted everything — or a stub factory that
    silently built nothing — would keep both tests above green while the shim
    they describe had been deleted.
    """
    with pytest.raises(SystemExit) as excinfo:
        _cli_parser().parse_args(["dashboard", "--no-such-flag"])

    assert excinfo.value.code == 2


def test_the_cli_wires_this_same_parser_factory():
    """The factory under test must be the one an old app shell's argv reaches.

    Textual rather than an import of ``hermes_cli.main``: that module is ~12.8k
    lines with a heavy import graph, and paying it to learn one wiring fact
    would make a parser test the slowest file in this directory.
    """
    source = (REPO_ROOT / "hermes_cli" / "main.py").read_text(
        encoding="utf-8", errors="replace"
    )

    assert (
        "from hermes_cli.subcommands.dashboard import build_dashboard_parser"
        in source
    ), "hermes_cli.main no longer imports the dashboard parser factory"
    assert "build_dashboard_parser(" in source, (
        "hermes_cli.main imports the factory but never calls it — the argv this "
        "file parses would reach a different parser than the CLI builds"
    )
