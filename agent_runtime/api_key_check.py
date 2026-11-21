"""The ONE check an API key passes before it is saved or leased: no hidden character in it.

RT-FU-AN-API-KEY-WITH-A-HIDDEN-CONTROL-CHARACTER-IS-REFUSED-WHEN-IT-IS-SAVED (review w1118a.69): a
key pasted at ``hermes auth add`` kept a trailing NUL (``str.strip`` keeps one), was stored, and
every Anthropic call then failed in 0.05 s as ``APIConnectionError`` (``Illegal header value``) —
21 transport retries and a "no model provider is configured" chat, never the reason.

* :func:`clean_api_key` is what every save door the fork owns calls
  (``hermes_cli/auth_noninteractive.py::set_key``, so ``hermes harness auth set-key`` and
  ``runtime.provider.key.set``): surrounding whitespace is trimmed, and any other control or
  invisible format character refuses :data:`API_KEY_CONTROL_CHARACTER` with a plain reason.
* :func:`api_key_refusal` is the same rule at lease time (``agent/credential_pool.py``'s fork
  seam in ``_available_entries``): a key already stored with such a character reads DEAD with
  this reason at once, so the pool's row says why and the turn refuses naming it
  (``agent_runtime/provider_login_expiry.py``) instead of retrying the transport.

The upstream CLI prompt (``hermes_cli/auth_commands.py``, ``masked_secret_prompt(...).strip()``) is
upstream's own save door with no fork seam; what it stores is caught here at the first lease. The
upstream fix (refuse a control character after the prompt's ``strip``) is a PR to name, never an
upstream edit.

No function here logs, prints, raises or returns the key's text.
"""

from __future__ import annotations

import unicodedata
from typing import Optional

__layer__ = "models"

__all__ = ["API_KEY_CONTROL_CHARACTER", "ApiKeyRefused", "api_key_refusal", "clean_api_key"]

#: The typed reason a key with a hidden character is refused with, at save and at lease.
API_KEY_CONTROL_CHARACTER = "api_key_control_character"

#: Unicode categories no API key carries: controls (NUL, ESC, an interior CR/LF …), invisible
#: format characters (zero-width space, BOM, direction marks) and line/paragraph separators.
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})

_REFUSAL_MESSAGE = ("The API key contains a hidden character (often picked up when it was copied); "
                    "copy the key again and paste it.")


class ApiKeyRefused(ValueError):
    """A key the check refuses. ``reason`` is :data:`API_KEY_CONTROL_CHARACTER`; the text never
    carries the key."""

    def __init__(self, reason: str = API_KEY_CONTROL_CHARACTER):
        super().__init__(_REFUSAL_MESSAGE)
        self.reason = reason


def _hidden(text: str) -> bool:
    return any(unicodedata.category(ch) in _HIDDEN_CATEGORIES for ch in text)


def api_key_refusal(secret: object) -> Optional[str]:
    """:data:`API_KEY_CONTROL_CHARACTER` when *secret*, trimmed, still holds a hidden character,
    else None (a non-string reads None: there is no key text to judge)."""
    if not isinstance(secret, str):
        return None
    # MUTATION: return None here and test_a_stored_key_with_a_nul_reads_dead_at_its_first_lease reddens.
    return API_KEY_CONTROL_CHARACTER if _hidden(secret.strip()) else None


def clean_api_key(secret: str) -> str:
    """*secret* with surrounding whitespace trimmed; raises :class:`ApiKeyRefused` on a hidden character.

    ``str.strip`` trims spaces, tabs, CR and LF at the ends but keeps a NUL, a zero-width space
    or a BOM, so those are refused rather than trimmed: a key that held one may hold another
    inside, and the person is told to paste it again."""
    # MUTATION: drop .strip() here and test_set_key_trims_a_trailing_space_and_newline reddens.
    cleaned = secret.strip()
    if _hidden(cleaned):
        raise ApiKeyRefused()
    return cleaned
