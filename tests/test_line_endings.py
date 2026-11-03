"""No tracked text blob carries a carriage return, and the count can only fall.

W1-H3 slice 5. `tests/agent_runtime/test_office_store.py` was CRLF on `main`,
came back from a Mac-side edit as LF, and turned a +149-line stage into a
2513-line whole-file rewrite that no reviewer could read. It was restored to
CRLF so the landing diff stayed reviewable — a correct call for that landing
and a bad steady state, because it left the repo's endings a property of
whichever host last touched a file.

The census that settled it, run at `0c744aa586`: 8862 LF blobs against 33 CRLF
and 5 MIXED. Not one of the 38 had a claim to its endings. Each was a minority
outlier inside its own directory (2 CRLF against 64 LF under
`docs/.../archive/`, 2 against 125 at the repo root), the two root artifacts
arrived together in the fork-foundation import, and every Windows-only script
in the tree (`*.ps1`, `*.cmd`) was already LF. So the deliberate list is EMPTY
and the keeper set below says so rather than being quietly omitted — an empty
exception set that exists is a decision; one that does not exist is a gap.

This gate, not `.gitattributes`, is the enforcement. Attributes govern
conversion on check-in and checkout and say nothing about blobs already in the
object store — which is exactly how 38 of them sat there for months.

The INDEX is what is read (`i/` from `git ls-files --eol`), never the working
tree: a contributor with `core.autocrlf=true` has CRLF on disk by design and
has done nothing wrong. What must not vary is what gets committed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.gate


REPO_ROOT = Path(__file__).resolve().parent.parent

#: Paths whose committed CRLF is DELIBERATE. Adding one means adding a `-text`
#: rule to a `.gitattributes` too, and writing the reason here: a keeper without
#: a reason is indistinguishable from the accident this gate exists to catch.
DELIBERATE_CRLF: frozenset[str] = frozenset({
    # Upstream's own bytes (CRLF as upstream committed them); the fork stopped
    # carrying a normalising edit in an upstream file (lane FOOTPRINT-DROP,
    # 2026-09-27). Keeper: contributors/emails/.gitattributes.
    "contributors/emails/uperLu@users.noreply.github.com",
    # Eternia-Companion's Lens conformance oracle, copied byte-for-byte: Companion
    # commits these with CRLF and corpus_manifest.json pins Companion's own sha256
    # over those bytes, so normalising them would break the oracle pin. Their
    # `* -text` rule predates this entry (lens L0); the gate only lacked the name.
    # Keeper: tests/agent_runtime/lens/conformance/.gitattributes.
    "tests/agent_runtime/lens/conformance/episode_rearm_corpus.json",
    "tests/agent_runtime/lens/conformance/evidence_corpus.json",
    "tests/agent_runtime/lens/conformance/http_redaction_corpus.json",
    "tests/agent_runtime/lens/conformance/observation_corpus.json",
})

#: `git ls-files --eol` index states that mean "this blob carries CR".
#: `i/none` is a file with no line endings at all (a one-line file with no
#: trailing newline) and `i/-text` is a binary, neither of which is a claim
#: about endings.
CARRIES_CR = frozenset({"i/crlf", "i/mixed"})


#: The blob-keyed memo of ``git ls-files --eol``'s index states, beside the clone's object store
#: (``git rev-parse --git-common-dir``), shared by every worktree (FH-LINE-ENDINGS-GATE-OVER-30S-COLD).
EOL_MEMO_NAME = "hermes-eol-memo.json"
#: Paths per ``git ls-files --eol`` call for blobs the memo has not seen (argv stays far under any limit).
_EOL_BATCH = 500


def _git(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=False, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


def _staged_blobs() -> dict[str, str] | None:
    """``{path: blob sha}`` of the index, from ``ls-files -s`` (index only — no blob is read)."""

    done = _git("ls-files", "-s", "-z")
    if done.returncode != 0:
        return None
    out: dict[str, str] = {}
    for record in done.stdout.split("\0"):
        meta, tab, path = record.partition("\t")
        if tab:
            out[path] = meta.split()[1]
    return out


def _eol_states(paths: list[str]) -> dict[str, str]:
    """``{path: i/<state>}`` from git's own classifier, for ``paths`` only (literal pathspecs)."""

    states: dict[str, str] = {}
    for start in range(0, len(paths), _EOL_BATCH):
        done = _git("ls-files", "--eol", "-z", "--", *paths[start:start + _EOL_BATCH],
                    env={"GIT_LITERAL_PATHSPECS": "1"})
        if done.returncode != 0:
            pytest.skip(f"git ls-files --eol failed: {done.stderr.strip()}")
        for record in done.stdout.split("\0"):
            columns, tab, path = record.partition("\t")
            if tab:
                states[path] = columns.split()[0]
    return states


def _memo_path() -> Path | None:
    done = _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(done.stdout.strip()) / EOL_MEMO_NAME if done.returncode == 0 and done.stdout.strip() else None


def _read_memo(path: Path | None) -> dict[str, str]:
    import json

    try:
        held = json.loads(path.read_text(encoding="utf-8")) if path is not None else {}
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in held.items()} if isinstance(held, dict) else {}


def _write_memo(path: Path | None, memo: dict[str, str]) -> None:
    import json
    import os

    if path is None:
        return
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(memo, sort_keys=True), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)


def _index_line_endings() -> dict[str, str]:
    """Every tracked path's INDEX end-of-line state.

    ``git ls-files --eol`` reads every blob to classify it: one call over the whole tree took 87 s cold at
    load ~50 (FH-LINE-ENDINGS-GATE-OVER-30S-COLD; the per-file spelling before it took minutes). A blob's
    state is a function of its bytes, so the answer is memoised by BLOB SHA beside the object store: the
    index listing (``ls-files -s``, no blob read) names every blob, and only blobs the memo has not seen
    are classified — by git's own ``--eol``, never a re-implementation of its text detection.
    """

    blobs = _staged_blobs()
    if blobs is None:
        pytest.skip("git ls-files -s failed")
    memo_path = _memo_path()
    memo = _read_memo(memo_path)
    unseen = sorted(path for path, sha in blobs.items() if sha not in memo)
    if unseen:
        for path, state in _eol_states(unseen).items():
            if path in blobs:
                memo[blobs[path]] = state
        _write_memo(memo_path, memo)
    return {path: memo[sha] for path, sha in blobs.items() if sha in memo}


@pytest.fixture(scope="module")
def endings() -> dict[str, str]:
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    states = _index_line_endings()
    # A collapse to a handful of rows means the parse drifted, not that the
    # tree emptied. Without this the assertion below passes vacuously on any
    # git output shape this stops understanding.
    assert len(states) > 5000, f"only {len(states)} tracked paths — the parse drifted"
    return states


def test_no_tracked_blob_carries_a_carriage_return_unless_it_is_declared(endings):
    """The pin. 38 CR-carrying blobs became 0, and 0 is now the ratchet."""

    carrying = sorted(
        path for path, state in endings.items() if state in CARRIES_CR
    )
    undeclared = [path for path in carrying if path not in DELIBERATE_CRLF]

    assert undeclared == [], (
        "these blobs carry CRLF in the INDEX and are not declared deliberate: "
        f"{undeclared}. Normalize them (read bytes, replace b'\\r\\n' with "
        "b'\\n', write bytes) or add each to DELIBERATE_CRLF with its reason "
        "and a `-text` rule in .gitattributes."
    )


def test_a_declared_keeper_must_actually_be_tracked_and_actually_carry_cr(endings):
    """The other direction, so the keeper set cannot rot into a wish list.

    A path that was normalized, renamed, or deleted while still sitting in
    DELIBERATE_CRLF is a standing exemption for nothing — and the next real
    accident at that path would be waved straight through.
    """

    for path in sorted(DELIBERATE_CRLF):
        assert path in endings, f"declared CRLF keeper is not tracked: {path}"
        assert endings[path] in CARRIES_CR, (
            f"declared CRLF keeper no longer carries CR: {path} ({endings[path]}) "
            "— drop it from DELIBERATE_CRLF"
        )


def test_the_byte_pinned_office_layout_goldens_are_still_lf(endings):
    """The one place in this repo where bytes are a contract: the cross-repo
    placement goldens are `-text` and byte-identical to the launcher's copy,
    with both `MANIFEST.sha256` files carrying the same digest. `-text` means
    git converts nothing in either direction — so what it holds is whatever was
    committed, and the new repo-wide `* text=auto eol=lf` must not have moved
    it. This asserts the bytes it actually holds, LF, rather than trusting rule
    precedence.
    """

    goldens = {
        path: state
        for path, state in endings.items()
        if path.startswith("tests/fixtures/office_layout/")
    }

    assert goldens, "the byte-pinned goldens moved; re-point this pin"
    assert not [path for path, state in goldens.items() if state in CARRIES_CR]


def test_the_blob_memo_answers_what_git_answers(endings):
    """FH-LINE-ENDINGS-GATE-OVER-30S-COLD: the memo is git's own classification keyed by blob, never a guess.
    Mutation: key the memo by path instead of blob sha -> the memo answers nothing, red."""

    sample = sorted(endings)[:: max(1, len(endings) // 200)]
    assert _eol_states(sample) == {path: endings[path] for path in sample}


def test_a_blob_the_memo_has_seen_is_not_classified_again(endings, monkeypatch):
    """Mutation: classify every staged path, not only the unseen ones -> the tripwire fires, red."""

    def tripwire(paths):
        raise AssertionError(f"re-classified {len(paths)} seen blob(s)")

    monkeypatch.setitem(globals(), "_eol_states", tripwire)
    assert _index_line_endings() == endings
