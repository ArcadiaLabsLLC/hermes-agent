"""Fork half of the ``_live_system_guard`` argv classifier in ``tests/conftest.py``.

A multi-line script's shell COMMENTS are not commands: prose like
"Hermes loads $HERMES_HOME/.env" followed anywhere later by the word "gateway"
used to read as ``hermes ... gateway`` (fork-hygiene 2026-09-24,
docker/stage2-hook.sh's keygen block). Kept here so the upstream conftest
carries a one-line call rather than the helper (the ``[up-fp]`` ratchet).
"""

from __future__ import annotations


def strip_shell_comments(script: str) -> str:
    """*script* with each ``#`` comment removed, the way sh reads one: a ``#``
    that begins a word and is outside quotes runs to end of line."""
    kept = []
    for line in script.splitlines():
        quote = None
        cut = len(line)
        for index, char in enumerate(line):
            if quote:
                if char == quote:
                    quote = None
            elif char in ("'", '"'):
                quote = char
            elif char == "#" and (index == 0 or line[index - 1].isspace()):
                cut = index
                break
        kept.append(line[:cut])
    return "\n".join(kept)


def script_words(token: str) -> list[str]:
    """Whitespace words of one argv token; a script token (one with a newline)
    loses its comments first, a single-line argv token is split as it was."""
    if "\n" in token:
        token = strip_shell_comments(token)
    return token.split()
