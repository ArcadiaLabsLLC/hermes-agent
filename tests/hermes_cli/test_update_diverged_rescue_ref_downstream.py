"""Fork half of upstream's ``test_update_diverged_rescue_ref.py`` (lane REDS3).

The fixture's ``origin`` is a local path, which ``_is_fork`` reads as a fork, and
the fork never resets a diverged fork checkout: ``_reconcile_diverged_checkout``
hands it to ``update_history.guard_fork_history``, which parks review refs and
exits ``HISTORY_REVIEW_EXIT`` (adopted in 1487c101ee). The upstream id is a strict
xfail in ``tests/_downstream/id_markers.py``; these two pin both branches.
"""

from __future__ import annotations

import pytest

from hermes_cli import update_cmd
from hermes_cli.update_history import HISTORY_REVIEW_EXIT
from tests.hermes_cli.test_update_diverged_rescue_ref import (  # noqa: F401 — the fixture
    GIT,
    _assert_reset_kept_local_commit,
    _git,
    diverged_checkout,
)


def _pull(checkout, monkeypatch):
    monkeypatch.setattr(update_cmd._m(), "PROJECT_ROOT", checkout)
    update_cmd._pull_updates(
        GIT, "main", None, prompt_for_restore=False, gw_input_fn=None,
        discard_local_changes=False, keep_stash=False)


def test_a_diverged_fork_checkout_is_preserved_for_review(diverged_checkout, monkeypatch, capsys):
    """The fork branch: no reset, the local commit stays checked out, exit 2."""
    checkout, local_sha = diverged_checkout

    with pytest.raises(SystemExit) as exc:
        _pull(checkout, monkeypatch)

    assert exc.value.code == HISTORY_REVIEW_EXIT
    assert _git(checkout, "rev-parse", "HEAD").stdout.strip() == local_sha


def test_upstreams_rescue_ref_path_holds_for_an_official_origin(diverged_checkout, monkeypatch, capsys):
    """Positive control: with the origin read as official, upstream's assertions hold verbatim."""
    checkout, local_sha = diverged_checkout
    monkeypatch.setattr(update_cmd, "_is_fork", lambda origin_url: False)

    _pull(checkout, monkeypatch)

    out = capsys.readouterr().out
    _assert_reset_kept_local_commit(checkout, local_sha, out)
    assert "1 commit(s) not on origin/main" in out
