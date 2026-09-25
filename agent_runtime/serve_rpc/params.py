"""Typed parameter readers shared by the verb families: workspace ids, the
correlation id, and the level/map expectation and id parameters.

Pure: each reader validates one key and either returns the value or refuses
with a reason the handler turns into ``-32602``.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, ERR_NOT_FOUND, err

__layer__ = "policy"

__all__ = [
    "CORRELATION_ID_INVALID_REASON",
    "_CorrelationIdRefused",
    "_LevelExpectationRefused",
    "_correlation_id_param",
    "_level_expect_param",
    "_level_workspace_id_or_error",
    "_level_workspace_missing",
    "_map_expect_param",
    "_map_id_or_error",
    "_map_id_param",
    "_workspace_id_param",
]


# ── methods ──────────────────────────────────────────────────────────────────


def _workspace_id_param(params: dict) -> str | None:
    raw = params.get("workspace_id")
    if not isinstance(raw, str):
        return None
    return raw.strip() or None


#: The one ``data.reason`` every write verb spends for a malformed gesture token,
#: so a client decoder branches on a single stable string across all four.
CORRELATION_ID_INVALID_REASON = "correlation_id_invalid"


class _CorrelationIdRefused(Exception):
    """A gesture token that failed boundary validation, carrying its message."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _correlation_id_param(params: dict) -> str | None:
    """The gesture's correlation token off ``params``, or ``None`` when absent.

    THE boundary for EG-2.3's id (Plan D §V1/§V2). Absent is the normal case and
    means "no gesture behind this write" — every downstream payload then stays
    byte-identical to what it was before this key existed, which is what makes the
    whole change additive.

    A PRESENT-but-illegal token is REFUSED rather than dropped, and that asymmetry
    against :func:`state_patches.normalize_correlation_id`'s silent drop is
    deliberate: this lane has a reply channel, so a client that sent free text
    where a generated token belongs gets told so instead of quietly diagnosing
    with an id the server discarded. Nothing is sanitized — a repaired id would
    print a value neither side used, which is worse than no id at all.

    Raises :class:`_CorrelationIdRefused`; every caller translates it to the same
    ``-32602`` / :data:`CORRELATION_ID_INVALID_REASON` pair.
    """

    from agent_runtime.state_patches import (
        CORRELATION_ID_MAX_LEN,
        normalize_correlation_id,
    )

    raw = params.get("correlation_id")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise _CorrelationIdRefused(
            "invalid params: correlation_id must be a string or omitted"
        )
    token = normalize_correlation_id(raw)
    if token is None:
        raise _CorrelationIdRefused(
            "invalid params: correlation_id must be a generated token of at most "
            f"{CORRELATION_ID_MAX_LEN} characters from [A-Za-z0-9_.:-]"
        )
    return token


class _LevelExpectationRefused(Exception):
    """An ``expect_sha256`` that failed boundary validation."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _level_expect_param(params: dict) -> tuple[bool, str | None]:
    """``(provided, value)`` for ``expect_sha256``.

    The key's PRESENCE is the third state and it cannot be folded into the
    value: omitted means unconditional and ``null`` means "there must be nothing
    stored", and a lane that read them as the same thing would turn every first
    write into an unguarded one.

    A non-hex string is refused here rather than carried to the comparison,
    where it could only ever produce a mismatch — and a mismatch is reported as
    a CONFLICT, which would tell a client with a typo'd token that somebody else
    had written their level.
    """

    if "expect_sha256" not in params:
        return False, None
    raw = params.get("expect_sha256")
    if raw is None:
        return True, None
    if not isinstance(raw, str):
        raise _LevelExpectationRefused(
            "invalid params: expect_sha256 must be a sha256 hex string, null or omitted"
        )
    token = raw.strip()
    if len(token) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in token):
        raise _LevelExpectationRefused(
            "invalid params: expect_sha256 must be 64 hex characters, null or omitted"
        )
    return True, token


def _level_workspace_missing(rid: Any, workspace_id: str) -> dict | None:
    """The unknown-workspace refusal, or ``None`` when the record resolves.

    Keyed on the workspace RECORD and not on a stored level, because absence of
    a level is the normal case: most workspaces never had one applied, and
    ``present: false`` is this family's honest empty. What must never be an
    honest empty is a TYPO — the read leg answering a blank for a workspace id
    that does not exist is the same defect ``runtime.office.get`` refuses, one
    family over.
    """

    from agent_runtime import paths

    if paths.workspace_path(workspace_id).is_file():
        return None
    return err(
        rid,
        ERR_NOT_FOUND,
        f"unknown workspace: {workspace_id}",
        {"reason": "workspace_not_found", "workspace_id": workspace_id},
    )


def _level_workspace_id_or_error(rid: Any, params: dict) -> tuple[str | None, dict | None]:
    """``(workspace_id, error_frame)`` — one spelling for all three verbs."""

    workspace_id = _workspace_id_param(params)
    if workspace_id is None:
        return None, err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: workspace_id must be a non-empty string",
            {"reason": "workspace_id_required"},
        )
    return workspace_id, _level_workspace_missing(rid, workspace_id)


def _map_expect_param(params: dict) -> tuple[bool, str | None]:
    """``(provided, value)`` for ``expect_sha256`` — the level lane's three states.

    Shares ``_LevelExpectationRefused`` rather than minting a twin: the refusal
    is the same refusal in the same words, and two exception types for one
    condition is how two lanes start disagreeing about which one a client saw.
    """

    return _level_expect_param(params)


def _map_id_param(params: dict) -> str | None:
    raw = params.get("map_id")
    if not isinstance(raw, str):
        return None
    return raw.strip() or None


def _map_id_or_error(rid: Any, params: dict) -> tuple[str | None, dict | None]:
    """``(map_id, error_frame)`` — one spelling for all four verbs."""

    map_id = _map_id_param(params)
    if map_id is None:
        return None, err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: map_id must be a non-empty string",
            {"reason": "map_id_required"},
        )
    return map_id, None
