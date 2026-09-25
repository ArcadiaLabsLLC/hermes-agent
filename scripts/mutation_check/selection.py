"""The claims file and git: which registered claims this diff selects.

Reads ``tests/mutation_claims.json`` and the exemptions file (JSON, dependency
free), asks git what the diff touched, and partitions every claim into selected
(by the anchor's own lines, or by its symbol) and unselected. The map is
``scripts/mutation_check/__init__.py``.
"""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .anchor import _anchor_or_raise
from .schema import (
    ANCHOR_KEY,
    DERIVED_AT_KEY,
    HUNK,
    NON_PRODUCTION_PREFIXES,
    PLATFORMS,
    REPO_ROOT,
    SELECTION_KEY,
)

__layer__ = "stores"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain an object")
    return value


def _changed_sources(base: str) -> list[str]:
    """The production ``.py`` files this diff touched, sorted.

    Deletions are excluded (``--diff-filter=d``): a file that is gone cannot
    carry an anchor, so listing it as unregistered would ask for a claim nobody
    can write.
    """

    completed = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=d", base, "--", "*.py"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git diff --name-only failed: {completed.stderr.strip()}")
    return sorted(
        path
        for path in (row.strip().replace("\\", "/") for row in completed.stdout.splitlines())
        if path and not path.startswith(NON_PRODUCTION_PREFIXES)
    )


def _changed_lines(base: str, relative_path: str) -> set[int]:
    completed = subprocess.run(
        ["git", "diff", "--unified=0", base, "--", relative_path],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git diff failed for {relative_path}: {completed.stderr.strip()}")
    changed: set[int] = set()
    for row in completed.stdout.splitlines():
        match = HUNK.match(row)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        if count == 0:
            # A DELETION-ONLY hunk (`@@ -32 +31,0 @@`): nothing was added, so
            # `range(31, 31)` is empty and this hunk used to contribute no
            # changed line at all. Every retirement wave therefore reported
            # `candidates: 0` and shipped with zero mutation coverage BY
            # CONSTRUCTION — measured on the Z1 landing (`4bf4387760`), filed
            # the same day.
            #
            # The two new-file lines the removed text sat between are what is
            # left of it, and they are what a claim anchored beside the
            # deletion overlaps. Paired with symbol-scoped selection below,
            # this is also how a deletion INSIDE a symbol reaches that symbol's
            # claims, which is the case the row actually cared about.
            changed.update({max(start, 1), start + 1})
            continue
        changed.update(range(start, start + count))
    return changed


def _validate_exemptions(path: Path) -> None:
    # JSON is valid YAML; keeping this dependency-free lets the selector run
    # before CI installs the repository environment.
    rows = _load_json(path).get("exemptions", [])
    if not isinstance(rows, list):
        raise RuntimeError(f"{path}: exemptions must be a list")
    required = {"id", "path", "symbol", "operator", "reason", "owner", "issue", "expires"}
    allowed_reasons = {"equivalent", "observability-only", "generated", "contract-out-of-scope"}
    for row in rows:
        if not isinstance(row, dict) or not required.issubset(row):
            raise RuntimeError(f"{path}: every exemption needs {sorted(required)}")
        if row["reason"] not in allowed_reasons:
            raise RuntimeError(f"{path}: invalid reason for {row['id']}: {row['reason']}")
        try:
            expiry = date.fromisoformat(str(row["expires"]))
        except ValueError as error:
            raise RuntimeError(f"{path}: invalid expiry for {row['id']}") from error
        if expiry < date.today():
            raise RuntimeError(f"{path}: exemption expired: {row['id']} ({expiry})")


def _current_platform() -> str:
    return "windows" if os.name == "nt" else "posix"


def _declared_platforms(claim: dict[str, Any]) -> frozenset[str] | None:
    """The hosts this claim is about, or ``None`` for "every host".

    Optional and absent from 112 of 113 rows, which is the right default: a
    claim that does not say otherwise is a claim about behaviour, and
    behaviour is not supposed to have a platform.
    """

    raw = claim.get("platforms")
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw or not all(isinstance(row, str) for row in raw):
        raise RuntimeError(
            f"{claim['id']}: platforms must be a non-empty list of strings"
        )
    unknown = sorted(set(raw) - PLATFORMS)
    if unknown:
        raise RuntimeError(
            f"{claim['id']}: unknown platforms {unknown}; known: {sorted(PLATFORMS)}"
        )
    return frozenset(raw)


def _partition_claims(
    base: str, claims_path: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every claim, split into the ones this diff selects and the ones it does not.

    The unselected half is RETURNED rather than dropped on the floor. A claim
    whose ``find`` still resolves but whose line the diff never touched is not
    an error and must not be run — but it is also not nothing: it is a
    registered guarantee that this run did not exercise, and a reader who sees
    only the selected list cannot tell it apart from a claim that was never
    written. Measured on the S4 landing, where
    ``s4-a-pre-plan-done-receipt-re-enters-the-skills-phase`` anchors a line the
    slice did not change and therefore never appeared in any output at all.

    Selection is by SYMBOL, not by the anchor's own two lines. The measured
    miss (H-H2, `0ecb921b9d`): that landing rewrote 82 lines of
    ``agent_create.py``, 41 of them inside ``_reply``, and rendered the exact
    two lines ``hh2-the-one-reply-builder-stops-observing-the-revision``
    anchors on (1170-1171) as unchanged CONTEXT. The claim registered FOR that
    slice was not selected by its own landing diff, and the gate said so with a
    green run. A guarantee is about a symbol's behaviour, so a diff that
    rewrote the symbol has to put it on the hook whether or not the two lines
    carrying the needle happened to survive the rewrite verbatim.

    ``module``-scope claims keep line selection: their span is the whole file,
    and "this diff touched this file" would select them on every run — which is
    not a symbol claim, it is no claim at all.
    """

    rows = _load_json(claims_path).get("claims", [])
    if not isinstance(rows, list):
        raise RuntimeError(f"{claims_path}: claims must be a list")
    selected: list[dict[str, Any]] = []
    unselected: list[dict[str, Any]] = []
    for claim in rows:
        if not isinstance(claim, dict):
            raise RuntimeError(f"{claims_path}: claim rows must be objects")
        required = {"id", "path", "symbol", "operator", "find", "replace", "test"}
        if not required.issubset(claim):
            raise RuntimeError(f"{claims_path}: claim needs {sorted(required)}")
        # Unknown fields are refused, not ignored. `platform: "posix"` for
        # `platforms: ["posix"]` is the typo this schema invites, and an
        # ignored field would mean the claim runs on every host while its
        # author believes it is scoped — a silent SURVIVED waiting to happen.
        unknown = sorted(set(claim) - required - {"platforms", DERIVED_AT_KEY})
        if unknown:
            raise RuntimeError(f"{claims_path}: {claim['id']}: unknown claim fields: {unknown}")
        _declared_platforms(claim)
        anchor, _ = _anchor_or_raise(claim)
        # Carried on the row so the mutate loop splices the anchor this
        # selection was computed from, rather than re-deriving one and hoping
        # the two agree.
        claim[ANCHOR_KEY] = anchor
        changed = _changed_lines(base, str(claim["path"]))
        if anchor.lines & changed:
            claim[SELECTION_KEY] = "lines"
            selected.append(claim)
        elif anchor.symbol_lines & changed:
            claim[SELECTION_KEY] = "symbol"
            selected.append(claim)
        else:
            unselected.append(claim)
    return selected, unselected


def _commits_since_derivation(claim: dict[str, Any]) -> int | None:
    """How many commits have touched this claim's file since it was derived.

    ``None`` when there is nothing to say: no :data:`DERIVED_AT_KEY` on the row
    (the pre-schema majority), or a commit git cannot resolve in this checkout —
    a shallow clone and a worktree that has not fetched the sha are both normal,
    and neither is a fact about the claim. A count of ``0`` is a real answer and
    a different one: derived here, nothing has moved.

    Deliberately counts COMMITS TO THE FILE and not to the symbol. A per-symbol
    read would need the anchor resolved at the old commit — a checkout per claim
    — to say something this report is not entitled to say anyway: the output is
    a prompt to a human re-derivation, and "this file has moved 14 times since
    anyone looked at this needle" is enough to prompt one.
    """

    derived_at = str(claim.get(DERIVED_AT_KEY, "") or "").strip()
    if not derived_at:
        return None
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"{derived_at}..HEAD", "--", str(claim["path"])],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return len([line for line in result.stdout.splitlines() if line.strip()])


def _symbol_head(claim: dict[str, Any]) -> str:
    """The dotted half of ``symbol`` — the part that resolves to a definition."""

    return str(claim["symbol"]).split("/", 1)[0].strip()


def _path_matches(path: str, wanted: str) -> bool:
    """``wanted`` names ``path``: as itself, as a directory over it, or as a tail.

    The tail spelling (``agent_create.py`` for
    ``agent_runtime/agent_create.py``) is here because it is what a person
    about to rewrite a function actually types, and the alternative is a
    pre-flight nobody runs. Segment-aligned, so ``create.py`` does not match
    ``agent_create.py``.
    """

    if path == wanted:
        return True
    if path.startswith(wanted.rstrip("/") + "/"):
        return True
    return path.endswith("/" + wanted)


def _symbol_matches(head: str, wanted: str) -> bool:
    """``wanted`` names the symbol ``head``, its owner, or one of its members.

    Three directions on purpose: the exact name, the bare name of a qualified
    one (``upsert_actor`` for ``OfficeStore.upsert_actor``, which is how the
    older claims are spelled), and a class naming everything anchored inside
    it — "I am about to rewrite ``OfficeStore``" is a real question and the
    answer is every method's claims.
    """

    return head == wanted or head.endswith("." + wanted) or head.startswith(wanted + ".")
