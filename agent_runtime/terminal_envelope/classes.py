"""The command-class taxonomy: the governed lane, the four classes, and the classifier.

VOCABULARY/TABLE module (sheet ``terminal_envelope.md`` §1): the classes, the
grantable set, the legacy reason and summary tables, the pattern mirror of
``tools/terminal_tool.py``'s block table, ``classify_command``.
"""

from __future__ import annotations

import re
from typing import Mapping

__layer__ = "models"



# ── the lane this slice governs ─────────────────────────────────────────────
#
# Same spelling as ``mcp_admission.LANE_MISSION_CHAT`` — the runtime surface a
# persona turn runs on, distinct from ``mcp_lane``'s entry-point lane. Mirrored
# rather than imported, and FENCED like every other deliberate mirror in this
# repo: ``tests/agent_runtime/test_mirrored_constant_fences.py`` asserts the two
# spellings are equal, so a one-sided edit to this wire token goes red.

LANE_MISSION_CHAT = "mission_chat"

#: Lanes whose gated classes an operator GRANT table can lift. Deliberately ONE
#: lane: the operator ruling makes mission-chat the primary work lane, and it is
#: the only lane where a config edit can allow a gated class. Widening this is a
#: product decision, not a config edit.
GOVERNED_LANES = frozenset({LANE_MISSION_CHAT})


# ── command-class taxonomy ──────────────────────────────────────────────────
#
# These are the classes the envelope ALREADY distinguishes. Nothing is invented
# here: every class below is one row (or one adjacent group of rows) of
# ``tools/terminal_tool.py::_HARNESS_BLOCK_PATTERNS``, and every class maps
# back to the exact legacy reason code that table returns, so the audit lane
# and every existing consumer keep reading the vocabulary they already read.

GIT_PUSH = "git_push"
DESTRUCTIVE_GIT = "destructive_git"
RECURSIVE_DELETE = "recursive_delete"
NETWORK_EGRESS = "network_egress"

COMMAND_CLASSES: frozenset[str] = frozenset(
    {
        GIT_PUSH,
        DESTRUCTIVE_GIT,
        RECURSIVE_DELETE,
        NETWORK_EGRESS,
    }
)

#: Classes an operator grant may cover. Ruling R-2 removed the former secret
#: read/exfiltration and production-operation floors from this taxonomy, so all
#: remaining envelope classes are grantable.
GRANTABLE_COMMAND_CLASSES: frozenset[str] = COMMAND_CLASSES

#: Class → the legacy ``_HARNESS_BLOCK_PATTERNS`` reason code. Preserved
#: verbatim so ``blocked_tool_attempts.jsonl`` readers, operator dashboards and
#: the existing envelope tests keep seeing the vocabulary they already parse.
#: ``destructive_git`` and ``recursive_delete`` intentionally SHARE
#: ``tree_wipe_blocked`` — the legacy table did not distinguish them, and the
#: finer split exists so a grant can name one without granting the other.
LEGACY_REASON_BY_CLASS: Mapping[str, str] = {
    GIT_PUSH: "git_push_requires_operator_approval",
    DESTRUCTIVE_GIT: "tree_wipe_blocked",
    RECURSIVE_DELETE: "tree_wipe_blocked",
    NETWORK_EGRESS: "network_command_requires_allowlist",
}

#: Human-facing one-liners for the refusal an AGENT reads.
CLASS_SUMMARY: Mapping[str, str] = {
    GIT_PUSH: "publishes commits to a remote",
    DESTRUCTIVE_GIT: "discards uncommitted or committed work in the git tree",
    RECURSIVE_DELETE: "recursively deletes a directory tree",
    NETWORK_EGRESS: "reaches a network host outside the loopback allowlist",
}

_NETWORK_ALLOWLIST = ("localhost", "127.0.0.1", "::1", "host.docker.internal")

#: MIRROR of ``tools/terminal_tool.py::_HARNESS_BLOCK_PATTERNS``, re-keyed from
#: reason code to command class. We mirror rather than import because
#: ``tools.terminal_tool`` is an upstream module whose import pulls in the whole
#: terminal backend stack (docker/modal/singularity probes), and this module is
#: imported by config/policy readers that must stay cheap. Drift is guarded by
#: ``tests/agent_runtime/test_terminal_envelope_grants.py::
#: test_class_patterns_mirror_the_legacy_envelope_table``, which asserts both
#: tables reach the same verdict over a shared corpus.
_CLASS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgit\s+push\b", re.IGNORECASE), GIT_PUSH),
    (re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE), DESTRUCTIVE_GIT),
    (re.compile(r"\bgit\s+reset\s+--(?:merge|keep)\b", re.IGNORECASE), DESTRUCTIVE_GIT),
    (re.compile(r"\bgit\s+clean\b[^\n;&|]*(?:-[^\s]*[xdf]|/[xdf])", re.IGNORECASE), DESTRUCTIVE_GIT),
    (re.compile(r"\bgit\s+checkout\b[^\n;&|]*\s(?:--force|-f)\b", re.IGNORECASE), DESTRUCTIVE_GIT),
    (
        re.compile(
            r"\bgit\s+checkout\b[^\n;&|]*(?:\s--(?:\s|$)|\s--(?:pathspec-from-file|pathspec-file-nul)\b)",
            re.IGNORECASE,
        ),
        DESTRUCTIVE_GIT,
    ),
    (re.compile(r"\bgit\s+checkout\b[^\n;&|]*\s(?:\.|:/|:\\)(?:\s|$)", re.IGNORECASE), DESTRUCTIVE_GIT),
    (re.compile(r"\bgit\s+switch\b[^\n;&|]*\s(?:--force|-f)\b", re.IGNORECASE), DESTRUCTIVE_GIT),
    (re.compile(r"\bgit\s+restore\b", re.IGNORECASE), DESTRUCTIVE_GIT),
    (re.compile(r"\bgit\s+stash\s+(?:drop|clear)\b", re.IGNORECASE), DESTRUCTIVE_GIT),
    (re.compile(r"\brm\s+-[^\n;&|]*r[^\n;&|]*f\b", re.IGNORECASE), RECURSIVE_DELETE),
    (re.compile(r"\bRemove-Item\b[^\n;&|]*(?:-Recurse|-r)\b", re.IGNORECASE), RECURSIVE_DELETE),
)

_NETWORK_TOOL_RE = re.compile(r"\b(curl|wget|iwr|Invoke-WebRequest|Invoke-RestMethod)\b", re.IGNORECASE)
_NETWORK_URL_RE = re.compile(r"https?://([^/\s'\"`]+)", re.IGNORECASE)


def classify_command(command: str) -> str | None:
    """The envelope-gated class this command falls in, or ``None``.

    Pure and side-effect free: same answer regardless of environment, lane or
    config. Whether a class is REFUSED is a separate question answered by
    :func:`envelope_decision`.
    """

    normalized = " ".join(str(command or "").strip().split())
    if not normalized:
        return None
    for pattern, command_class in _CLASS_PATTERNS:
        if pattern.search(normalized):
            return command_class
    return _network_class(normalized)


def _network_class(command: str) -> str | None:
    if not _NETWORK_TOOL_RE.search(command):
        return None
    hosts = _NETWORK_URL_RE.findall(command)
    if not hosts:
        return NETWORK_EGRESS
    for host in hosts:
        clean = host.split(":", 1)[0].strip("[]").lower()
        if clean not in _NETWORK_ALLOWLIST:
            return NETWORK_EGRESS
    return None


def legacy_reason_for_class(command_class: str | None) -> str | None:
    """The ``_HARNESS_BLOCK_PATTERNS`` reason code a class maps back to."""

    if not command_class:
        return None
    return LEGACY_REASON_BY_CLASS.get(command_class)
