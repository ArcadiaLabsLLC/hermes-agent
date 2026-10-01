"""Remember ``gettext.find`` answers for the life of one CLI process (HQ3, 2026-10-01).

Why this exists. ``argparse`` wraps every parser's group titles and help action in
``gettext.gettext``, and ``gettext`` keeps a cache only of translations it FOUND.
With no ``argparse.mo`` installed — the normal case — every call walks
``gettext.find`` again: one ``os.path.exists`` per locale variant per call. The
``hermes`` parser tree is about 620 parsers (three lookups each), so on a shell that
sets ``LANG`` (Git Bash, WSL, most terminals; ``en_US.UTF-8`` expands to four
variants) the tree costs ~7,450 file probes and, measured 2026-10-01 on Windows,
about 2.5 s of every non-``--version`` command. With ``LANG`` unset the probe loop
stops at ``C`` and the same tree costs ~0.1 s, which is why nobody saw it from cmd.

What it changes. Nothing a caller can observe except time: the answer for one
``(domain, localedir, languages, all)`` question — plus, when ``languages`` is not
given, the four locale variables ``find`` would read — is computed once and
replayed. A ``.mo`` file that appears mid-process is not noticed; no command
installs translations while it runs.

Stdlib only; installed by ``hermes_cli.main.main`` before the parser is built.
"""

from __future__ import annotations

import gettext
import os

__all__ = ["install_gettext_find_memo"]

#: The variables ``gettext.find`` reads when the caller passes no ``languages``,
#: in the order it reads them.
_LOCALE_ENV_KEYS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")


def install_gettext_find_memo() -> bool:
    """Replace ``gettext.find`` with a remembering wrapper. Idempotent.

    Returns ``True`` when this call installed it, ``False`` when it was already in place.
    """

    original = gettext.find
    if getattr(original, "__hermes_find_memo__", False):
        return False
    answers: dict = {}

    def find(domain, localedir=None, languages=None, all=False):  # noqa: A002 — gettext's own signature
        env = None if languages is not None else tuple(os.environ.get(key) for key in _LOCALE_ENV_KEYS)
        key = (domain, localedir, None if languages is None else tuple(languages), bool(all), env)
        try:
            answer = answers[key]
        except KeyError:
            answer = original(domain, localedir, languages, all)
            answers[key] = tuple(answer) if isinstance(answer, list) else answer
            return answer
        # ``all=True`` answers a list; hand each caller its own, as the original does.
        return list(answer) if isinstance(answer, tuple) else answer

    find.__hermes_find_memo__ = True
    find.__wrapped__ = original
    gettext.find = find
    return True
