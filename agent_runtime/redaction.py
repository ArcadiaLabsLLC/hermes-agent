from __future__ import annotations

import re
from functools import singledispatch
from pathlib import Path
from typing import Any, Callable


# ═══════════════════════════════════════════════════════════════════════════
# Secret-shaped assignment — ONE rule, ONE home.
# ═══════════════════════════════════════════════════════════════════════════
#
# THE DEFECT THIS MODULE RETIRES (2026-07-25)
# -------------------------------------------
# The runtime carried TWELVE independent spellings of "a secret-ish key,
# followed by a separator, followed by a value" — in ``realm_sync``,
# ``repo_context`` and ``stream``,
# ``profile_runner``, ``prompt_observability``, ``operator_channels``,
# ``persona_chat_continuity``, ``persona_chat_history``, ``snapshot``, and this
# module. Every single one wrote the separator as ``\s*[:=]``.
#
# That cannot match JSON. In ``{"token": "ghp_…"}`` the key's CLOSING QUOTE
# sits between the key word and the ``:``, so ``token\s*[:=]`` never fires.
# Confirmed empirically on all twelve:
#
#     token: ghp_abcdefghij1234567890              -> CAUGHT
#     {"token": "ghp_abcdefghij1234567890"}        -> MISSED
#     {"api_key": "sk-abcdefghij1234567890"}       -> MISSED
#     {"a": {"client_secret": "abcdefghij123456"}} -> MISSED
#
# Blast radius: EVERY realm-sync artifact is JSON (``store/workspaces/*.json``,
# ``store/realms/*.json``, board ``board.json`` + ``cards/*.json``, office
# ``office.json`` + ``actors/*.json``), so ``_assert_no_secret_artifacts`` was
# blind on the whole publish surface; and the redaction lanes surfaced
# JSON-encoded credentials verbatim into ``safe_details``, proof excerpts,
# prompt observability, and archived chat transcripts.
#
# THE FIX: :data:`SECRET_KEY_SEPARATOR`. Compose every rule from it. Never
# hand-roll ``\s*[:=]`` again — a thirteenth spelling is a thirteenth blind
# spot.
#
# GROUP CONTRACT (load-bearing — several call sites rebuild output as
# ``f"{match.group(1)}=[redacted]"``): the separator is a character class with
# a quantifier plus non-capturing groups ONLY. It never shifts group numbering.
# ``tests/agent_runtime/test_secret_assignment.py`` pins that for every pattern
# exported here.
SECRET_KEY_SEPARATOR = r"['\"]?\s*[:=]\s*"

# ── Key vocabularies ───────────────────────────────────────────────────────
# Three, not twelve. They differ on purpose:
#
#   GATE  — the realm-sync PUBLISH gate. Deliberately conservative: a match
#           hard-fails an operator's whole publish, so a false positive is a
#           denial-of-service on the feature. Paired with a long, restricted
#           value shape.
#   ENV   — env-var-shaped names (``HERMES_API_KEY``, ``DB_PASSWORD``), where
#           the secret word is a SEGMENT of a longer SCREAMING_SNAKE name.
#   TEXT  — prose/diagnostic redaction. The union of every vocabulary the
#           chat / prompt / repo-context lanes used. Redaction is display-only,
#           so over-matching costs readability, never safety — this one is
#           deliberately the broadest and, like the lanes it replaces, is NOT
#           anchored on ``\b`` (it matches ``xtoken:`` too, on purpose).
GATE_SECRET_KEYS = (
    r"api[_-]?key|authorization|bearer|client[_-]?secret|oauth[_-]?token"
    r"|password|private[_-]?key|secret|token"
)
ENV_SECRET_KEYS = (
    r"(?:[A-Za-z0-9]+_)*(?:SECRET|TOKEN|PASSWORD|PASS|CREDENTIAL|API_?KEY|KEY)(?:_[A-Za-z0-9]+)*"
)
TEXT_SECRET_KEYS = (
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token"
    r"|authorization|bearer|credential|passwd|password|secret|token"
)

# ── Composed patterns ──────────────────────────────────────────────────────

#: Realm-sync PUBLISH GATE (``_assert_no_secret_artifacts``) and realm-sync
#: ``_redact_text``. One group: the key word.
#:
#: The value shape (>= 16 chars of ``[A-Za-z0-9_./+=:-]``) is what keeps the
#: gate from refusing a publish over ``{"secret": false}`` or
#: ``{"token_count": 20208}``. It is load-bearing — do NOT relax it to a
#: permissive redaction value shape, or every realm publish becomes a coin
#: flip. Verified against 14,315 live JSON artifacts: zero false positives.
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(" + GATE_SECRET_KEYS + r")\b" + SECRET_KEY_SEPARATOR + r"['\"]?[A-Za-z0-9_./+=:-]{16,}"
)

#: Env-var-shaped redaction used by stream and packet projection.
#: One group: the full key (``HERMES_API_KEY``, not just ``API_KEY``).
ENV_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(" + ENV_SECRET_KEYS + r")" + SECRET_KEY_SEPARATOR + r"(?:\"[^\"]*\"|'[^']*'|[^\s'\"]+)"
)

#: Prose/diagnostic redaction, GREEDY value (``\S+`` — runs to whitespace).
#: Two groups: (1) key, (2) value. Used where the lane either drops the whole
#: line on a hit or rewrites it as ``key: [redacted]``, so swallowing trailing
#: punctuation costs nothing. Consumers: ``operator_channels``,
#: ``persona_chat_history``, ``snapshot``, ``persona_chat_continuity``.
TEXT_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(" + TEXT_SECRET_KEYS + r")" + SECRET_KEY_SEPARATOR + r"(\S+)"
)

#: Prose redaction, SURGICAL value (``[^\s,;]+`` — stops at a list separator).
#: Two groups: (1) key, (2) value. Used where the redacted text must stay
#: readable around the removed value — prompt capture and repo-context
#: excerpts that are fed back to an agent. Consumers: ``profile_runner``,
#: ``prompt_observability``, ``repo_context``.
TEXT_SECRET_VALUE_ASSIGNMENT_RE = re.compile(
    r"(?i)(" + TEXT_SECRET_KEYS + r")" + SECRET_KEY_SEPARATOR + r"([^\s,;]+)"
)

#: Every secret-assignment pattern this module owns. The group-contract test
#: iterates it, so a new pattern added here is automatically pinned.
ALL_SECRET_ASSIGNMENT_PATTERNS = (
    SECRET_ASSIGNMENT_RE,
    ENV_SECRET_ASSIGNMENT_RE,
    TEXT_SECRET_ASSIGNMENT_RE,
    TEXT_SECRET_VALUE_ASSIGNMENT_RE,
)


# ── label filters (moved in from profile_runner by lane R3) ──────────────────


def looks_sensitive_or_pathish(value: str) -> bool:
    """Does ``value`` look like a secret or a filesystem path? The progress/tool-IO
    label filter (lane R3 made ``profile_runner``'s copy this owner; the
    ``events``/``observability``/``progress`` copies fold onto it in their lanes)."""

    lowered = value.lower()
    if any(marker in lowered for marker in ("secret", "token", "password", "api_key", "apikey", "authorization", "bearer", "credential", "cookie", "private_key", "sk-")):
        return True
    if ":/" in value or "\\" in value or value.startswith(("/", "~")):
        return True
    if re.search(r"(^|\s)([A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+", value):
        return True
    return False


def safe_file_labels(value: Any) -> list[str]:
    """Bare file NAMES from a list of paths, dropping anything sensitive, pathish
    or outside ``[A-Za-z0-9_.-]{1,96}`` (same owner note as above)."""

    if not isinstance(value, list):
        return []
    labels: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        label = Path(text.replace("\\", "/")).name
        if not label or looks_sensitive_or_pathish(label):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", label):
            continue
        labels.append(label)
    return labels


#: The in-band marker a masked line is replaced by. One spelling for the read
#: projection (``persona_chat_history``) and the live mirror (``chat_live_log``).
REDACTED_SECRET_LINE = "[redacted line — contained a secret]"


def mask_secret_lines(text: str) -> str:
    """``text`` with every line that carries a secret assignment
    (:data:`TEXT_SECRET_ASSIGNMENT_RE`) replaced by :data:`REDACTED_SECRET_LINE`.

    The ONE per-line masker: the whole line goes, never a surgical cut, so a
    value the pattern half-matched cannot survive beside the key. Split and
    joined on ``\n`` only; callers normalize line endings, strip and bound.
    """

    return "\n".join(
        REDACTED_SECRET_LINE if TEXT_SECRET_ASSIGNMENT_RE.search(line) else line
        for line in text.split("\n")
    )


def scrub_tree(
    value: Any,
    *,
    scrub: Callable[[str], str],
    list_cap: int,
    leaf: Callable[[Any], Any] = lambda item: item,
) -> Any:
    """A JSON-shaped tree with every string passed through ``scrub``.

    The ONE walk (program §3 / sheet ``stream.md``): a mapping keeps its keys
    (as ``str``) and walks its values, a list or tuple becomes a list of at most
    ``list_cap`` walked items, a string is scrubbed, anything else goes through
    ``leaf``. The scrubber is the caller's — the patterns are single-homed here,
    but which one applies is the reader's question. Dispatch is the standard
    library's type table (``functools.singledispatch``), so a subclass takes its
    base's arm exactly as the ``isinstance`` ladder it replaces did.
    """

    return _scrub(value, scrub, list_cap, leaf)


@singledispatch
def _scrub(value: Any, scrub: Callable[[str], str], list_cap: int, leaf: Callable[[Any], Any]) -> Any:
    return leaf(value)


@_scrub.register(dict)
def _scrub_mapping(value: dict, scrub: Callable[[str], str], list_cap: int, leaf: Callable[[Any], Any]) -> Any:
    return {str(key): _scrub(item, scrub, list_cap, leaf) for key, item in value.items()}


@_scrub.register(list)
@_scrub.register(tuple)
def _scrub_sequence(value: Any, scrub: Callable[[str], str], list_cap: int, leaf: Callable[[Any], Any]) -> Any:
    return [_scrub(item, scrub, list_cap, leaf) for item in value[:list_cap]]


@_scrub.register(str)
def _scrub_text(value: str, scrub: Callable[[str], str], list_cap: int, leaf: Callable[[Any], Any]) -> Any:
    return scrub(value)
