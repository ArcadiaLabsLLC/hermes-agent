"""Whether the real upstream Telegram adapter's tests may skip (RT-MESSAGING-TESTS-NEED-THE-MESSAGING-EXTRA).

python-telegram-bot is the ``telegram`` extra, outside upstream's ``[all]`` (the 2026-05-12 policy in
``pyproject.toml``), so a venv built without it would SKIP the stranger-before-media pin and the token and
text log pins in silence. The fork's gate (``.github/workflows/fork-gates.yml`` ``validated-suite``) syncs
the extra and sets ``HERMES_REQUIRE_TELEGRAM_EXTRA=1``; there a missing library is a red, never a skip. The
canonical test venv's recipe (``docs/downstream-development.md``) carries the extra too.
"""

from __future__ import annotations

import os

import pytest

REQUIRE_ENV = "HERMES_REQUIRE_TELEGRAM_EXTRA"
REASON = ("python-telegram-bot is the `telegram` extra, outside `[all]`; these tests drive the real upstream "
          "adapter (RT-MESSAGING-TESTS-NEED-THE-MESSAGING-EXTRA)")


def require_telegram_extra() -> None:
    """Skip without python-telegram-bot — except where ``HERMES_REQUIRE_TELEGRAM_EXTRA=1``, which fails."""
    try:
        import telegram
    except ImportError:
        if os.environ.get(REQUIRE_ENV) == "1":
            pytest.fail(f"{REQUIRE_ENV}=1 and python-telegram-bot is not installed: {REASON}", pytrace=False)
        pytest.skip(REASON, allow_module_level=True)
