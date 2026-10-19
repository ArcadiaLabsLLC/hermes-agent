"""RT-NATIVE-WORKER-ENGINE-CPU: a worker spawned on a fresh home skips upstream's scratch prune.

``start_worker`` stamps a scratch dir that did not exist before the spawn (nothing can be
rooted in it, so the prune's host-wide ``psutil`` cwd pass finds nothing) and never stamps an
existing one. The stamp's name is upstream's, so the second half runs upstream's own
``get_scratch_dir`` the way a fresh worker process does and reads whether it pruned.

Killing mutations (recorded in the CHANGE commit): ``fresh_scratch`` forced True (an existing
scratch is stamped: its worker never prunes); ``SCRATCH_PRUNE_STAMP`` renamed (the worker
prunes the fresh home).
"""
from __future__ import annotations

import os
import time

import pytest

import hermes_constants
from agent_runtime.conversations import worker


class _Spawned(Exception):
    pass


def _spawn_until_the_process(monkeypatch, home):
    """``start_worker`` up to the spawn; the child is never started."""
    from hermes_cli.local_runtime import processes

    def refuse(*_args, **_kwargs):
        raise _Spawned

    monkeypatch.setattr(processes, "spawn_server", refuse)
    # The parent's own once-per-process prune is long spent in a serve.
    monkeypatch.setattr(hermes_constants, "_scratch_pruned_once", True)
    with pytest.raises(_Spawned):
        worker.start_worker(home, receive=lambda _frame: None, lost=lambda: None)


def _worker_process_prunes(monkeypatch, home) -> bool:
    """Whether upstream's boot-time ``get_scratch_dir`` prunes *home*, as in a fresh process."""
    pruned = []
    monkeypatch.setattr(hermes_constants, "_scratch_pruned_once", False)
    monkeypatch.setattr(hermes_constants, "prune_scratch_dir", lambda scratch=None, *a, **k: pruned.append(scratch))
    hermes_constants.get_scratch_dir(home)
    return bool(pruned)


def test_a_fresh_home_is_stamped_and_its_worker_skips_the_prune(tmp_path, monkeypatch):
    home = tmp_path / "fresh-profile"
    home.mkdir()
    _spawn_until_the_process(monkeypatch, home)
    assert (home / "cache" / "scratch" / worker.SCRATCH_PRUNE_STAMP).is_file()
    assert not _worker_process_prunes(monkeypatch, home)


def test_an_existing_scratch_is_never_stamped_and_its_worker_prunes(tmp_path, monkeypatch):
    home = tmp_path / "used-profile"
    scratch = home / "cache" / "scratch"
    (scratch / "old-entry").mkdir(parents=True)
    stamp = scratch / worker.SCRATCH_PRUNE_STAMP
    stamp.touch()
    old = time.time() - 2 * 3600
    os.utime(stamp, (old, old))
    _spawn_until_the_process(monkeypatch, home)
    assert stamp.stat().st_mtime == pytest.approx(old, abs=1)
    assert _worker_process_prunes(monkeypatch, home)
