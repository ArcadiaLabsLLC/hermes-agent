from __future__ import annotations

import json
import re
from functools import singledispatch
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__layer__ = "models"


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
#: ``prompt_observability``, and the test seam's repo-context excerpts
#: (``tests/_downstream/_seams.py``).
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


# ── transport diagnostics (folded in from ``mobile_core``'s ``redact.py``) ────
#
# The July mobile core carried three rules the patterns above do not cover,
# and embedded-hermes plan D0 folds them here before that copy is re-homed:
# a ``Bearer <token>`` credential written with a SPACE (the assignment patterns
# need ``:``/``=``), a credential HEADER whose vocabulary includes cookies, and
# signed URL query values (``X-Amz-Signature=…``, ``?key=…``). Plus the mapping
# rule: a value under a credential-named key is masked whatever its shape.

#: The in-band marker for a surgically removed transport credential.
REDACTED_VALUE = "[REDACTED]"

BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")

#: Two groups: (1) header name, (2) value.
CREDENTIAL_HEADER_RE = re.compile(
    r"(?i)\b(authorization|proxy-authorization|x-api-key|api-key|cookie|set-cookie)"
    r"\s*[:=]\s*([^\s,;]+)"
)

#: Query-parameter name fragments whose value is a signature or credential.
SIGNED_QUERY_MARKERS = (
    "signature", "credential", "security-token", "access_token",
    "api_key", "apikey", "token", "sig", "key",
)

#: Mapping keys whose value is a credential, spelled with ``-`` (``_`` folds).
CREDENTIAL_KEYS = frozenset({
    "authorization", "proxy-authorization", "api-key", "apikey", "x-api-key",
    "cookie", "set-cookie", "access-token", "refresh-token",
})

_URL_RE = re.compile(r"https?://[^\s\]\[<>{}\"']+")


def is_credential_key(key: Any) -> bool:
    """Is ``key`` a credential-bearing header or field name (``_`` and ``-`` alike)?"""

    return str(key).strip().lower().replace("_", "-") in CREDENTIAL_KEYS


def _signed_query_name(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith("x-amz-") or any(marker in lowered for marker in SIGNED_QUERY_MARKERS)


def redact_url(url: str) -> str:
    """``url`` with userinfo dropped and signed query values masked; shape kept."""

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return REDACTED_VALUE
    if not parts.scheme or not parts.netloc:
        return url
    host = f"{parts.hostname or ''}:{port}" if port else parts.hostname or ""
    query = [
        (name, REDACTED_VALUE if _signed_query_name(name) else value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, host, parts.path, urlencode(query), parts.fragment))


def redact_transport_text(value: str, *, secrets: tuple[str, ...] = ()) -> str:
    """Transport diagnostic text with bearer tokens, credential headers, signed
    URLs and each exact ``secrets`` value masked."""

    text = BEARER_TOKEN_RE.sub(f"Bearer {REDACTED_VALUE}", str(value))
    text = CREDENTIAL_HEADER_RE.sub(lambda match: f"{match.group(1)}: {REDACTED_VALUE}", text)
    text = _URL_RE.sub(lambda match: redact_url(match.group(0)), text)
    for secret in filter(None, secrets):
        text = text.replace(secret, REDACTED_VALUE)
    return text


def redact_transport_tree(value: Any) -> Any:
    """A JSON-safe copy of ``value``: credential-keyed values masked, every other
    string through :func:`redact_transport_text`, scalars kept, anything else
    stringified and redacted."""

    return _transport(value)


@singledispatch
def _transport(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_transport_text(str(value))


@_transport.register(dict)
def _transport_mapping(value: dict) -> Any:
    return {str(key): REDACTED_VALUE if is_credential_key(key) else _transport(item) for key, item in value.items()}


@_transport.register(list)
@_transport.register(tuple)
@_transport.register(set)
@_transport.register(frozenset)
def _transport_sequence(value: Any) -> Any:
    return [_transport(item) for item in value]


@_transport.register(str)
def _transport_text(value: str) -> Any:
    return redact_transport_text(value)


# ── secret VALUES in a tool's input or result (the operator tool-IO lane) ─────
#
# THE DEFECT THIS RETIRES (2026-10-02): the tool-IO lane blanked any LINE that
# contained a secret WORD. ``open_app_tab`` answered an auth refusal as one line
# of JSON whose prose said "no access token", and the operator console showed
# ``[redacted line — contained a secret]`` in place of the whole result —
# failure_class, message and next step included — while no secret was in it.
# A word is not a secret; a value is. So this lane scrubs VALUES: a mapping
# value under a secret-named field, a value written as a secret assignment in
# prose, a bearer/header credential, a signed URL, and the token shapes below.
# Field names and prose survive.

#: Field-name TAILS whose value is a secret, after camelCase/``-``/``.`` fold to
#: ``_``. A tail, not a substring: ``credential_profile`` and ``token_count``
#: name things that are not secrets; ``access_token`` and ``client_secret`` do.
SECRET_FIELD_TAILS = (
    "token", "secret", "password", "passwd", "passphrase", "authorization",
    "cookie", "credential", "credentials", "api_key", "apikey", "private_key",
    "access_key", "secret_key",
)

#: Credential SHAPES that are secrets wherever they appear, whatever they are
#: called: OpenAI/Anthropic-style ``sk-`` keys, GitHub tokens, Slack tokens, AWS
#: access key ids, Google API keys and JWTs.
SECRET_VALUE_SHAPE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"sk-[A-Za-z0-9_-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|AIza[0-9A-Za-z_-]{30,}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r")"
)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")


def is_secret_field_name(key: Any) -> bool:
    """Is ``key`` a field whose VALUE is a secret? Control characters are removed
    first, so ``"pass\\nword"`` is read as ``password``."""

    text = _CONTROL_CHARS_RE.sub("", str(key))
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text).lower()
    text = re.sub(r"[\s.\-]+", "_", text).strip("_")
    return any(text == tail or text.endswith(f"_{tail}") for tail in SECRET_FIELD_TAILS)


def _redact_assignment_value(match: re.Match[str]) -> str:
    value = match.group(2)
    if REDACTED_VALUE in value and not value.replace(REDACTED_VALUE, "", 1).strip("\"'}])"):
        return match.group(0)  # already scrubbed: a second pass changes nothing
    return f"{match.group(0)[: match.start(2) - match.start(0)]}{REDACTED_VALUE}"


def scrub_secret_values(text: str) -> str:
    """``text`` with every secret VALUE replaced by :data:`REDACTED_VALUE` and
    everything else -- field names, prose, line structure -- kept. Idempotent."""

    text = redact_transport_text(str(text))
    text = TEXT_SECRET_VALUE_ASSIGNMENT_RE.sub(_redact_assignment_value, text)
    return SECRET_VALUE_SHAPE_RE.sub(REDACTED_VALUE, text)


def scrub_secret_value_tree(value: Any) -> Any:
    """A JSON-shaped copy of ``value`` with secret VALUES replaced: a value under
    a secret-named field (a boolean or ``None`` there is a fact, not a secret,
    and is kept), and every string through :func:`scrub_secret_values`. A string
    that is itself a JSON object or array is decoded and walked, so a tool that
    answers ``{"error": "<json>"}`` is read field by field, not as one line."""

    if isinstance(value, dict):
        return {
            str(key): (
                REDACTED_VALUE
                if is_secret_field_name(key) and item is not None and not isinstance(item, bool)
                else scrub_secret_value_tree(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub_secret_value_tree(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            try:
                decoded = json.loads(stripped)
            except ValueError:
                decoded = None
            if isinstance(decoded, (dict, list)):
                return scrub_secret_value_tree(decoded)
        return scrub_secret_values(value)
    return value
