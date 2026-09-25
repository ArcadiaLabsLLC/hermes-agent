"""The fork's half of ``tests/hermes_cli/test_config_read_guard.py`` (lane CARRY2A).

The upstream guard is byte-identical to upstream and is a strict xfail by id
(``tests/_downstream/id_markers/``): the fork's
``agent_runtime/persona_config_sync.py`` reads a PULLED REALM SUBTREE's
``profiles/<name>/config.yaml`` with ``yaml.safe_load`` — a foreign, published
document that shares the filename, not this machine's user config (same class as
upstream's ``hermes_cli/managed_scope.py`` row). Routing it through the canonical
loaders would overlay this machine's managed scope and ``${ENV}`` expansion onto
somebody else's realm document, which ``read_remote_persona_defs()`` exists to
prevent.

This module runs upstream's OWN scan body with the fork's three differences
applied for the duration of one test:

* the allowlist gains ``agent_runtime/persona_config_sync.py``;
* ``.claude`` is pruned (ML-14 / B20(iii)): agent worktrees live under
  ``.claude/worktrees/<branch>/``, each a full copy of the repo whose files do
  not match the root-relative allowlist;
* any directory carrying ``pyvenv.cfg`` is pruned by marker, so an operator-named
  virtualenv (``.venv-ci``, ``venv/``) is not scanned as first-party source.
"""

from __future__ import annotations

import os
import types

import pytest

from tests.hermes_cli import test_config_read_guard as upstream

FORK_ALLOWLIST = {"agent_runtime/persona_config_sync.py"}
FORK_EXCLUDED_DIR_PARTS = {".claude"}
VENV_MARKER = "pyvenv.cfg"


def _walk_pruning_venvs(top, *args, **kwargs):
    """``os.walk`` that drops every PEP-405 environment before the caller sees it.

    Pruning in place keeps the yielded list the one ``os.walk`` descends by, so
    the upstream body's own ``dirnames[:] = ...`` still applies on top.
    """
    for dirpath, dirnames, filenames in os.walk(top, *args, **kwargs):
        dirnames[:] = [
            name for name in dirnames
            if not os.path.isfile(os.path.join(dirpath, name, VENV_MARKER))
        ]
        yield dirpath, dirnames, filenames


def _apply_fork_scope(monkeypatch):
    monkeypatch.setattr(upstream, "ALLOWLIST", upstream.ALLOWLIST | FORK_ALLOWLIST)
    monkeypatch.setattr(
        upstream, "EXCLUDED_DIR_PARTS", upstream.EXCLUDED_DIR_PARTS | FORK_EXCLUDED_DIR_PARTS
    )
    fork_os = types.SimpleNamespace(**{k: getattr(os, k) for k in dir(os) if not k.startswith("__")})
    fork_os.walk = _walk_pruning_venvs
    monkeypatch.setattr(upstream, "os", fork_os)


def test_no_raw_config_yaml_reads_outside_owner_modules_fork_scope(monkeypatch):
    _apply_fork_scope(monkeypatch)
    upstream.test_no_raw_config_yaml_reads_outside_owner_modules()


def test_the_walk_does_not_descend_into_a_repo_copy(tmp_path, monkeypatch):
    """``.claude/worktrees/<branch>/`` is a FULL COPY of this repo (B20(iii)); a
    ``pyvenv.cfg`` directory is an interpreter environment, not first-party source.

    Driven on a synthetic tree rather than on this checkout, because the hazard
    is intermittent: worktrees exist while agents are running and are pruned
    afterwards, so a witness that waited for the real thing would pass for the
    wrong reason most of the time. Both directions in one case: under the fork's
    scope the copy and the venv are invisible and the first-party file is not;
    under upstream's scope (the positive control) the same tree reaches all three.
    """
    offending = 'import yaml\n\nyaml.safe_load(open("config.yaml"))\n'
    (tmp_path / "some_package").mkdir()
    (tmp_path / "some_package" / "reader.py").write_text(offending, encoding="utf-8")
    copy = tmp_path / ".claude" / "worktrees" / "wave-2" / "gateway"
    copy.mkdir(parents=True)
    (copy / "config.py").write_text(offending, encoding="utf-8")
    venv = tmp_path / "venv-ci"
    (venv / "lib").mkdir(parents=True)
    (venv / VENV_MARKER).write_text("home = x\n", encoding="utf-8")
    (venv / "lib" / "vendored.py").write_text(offending, encoding="utf-8")
    monkeypatch.setattr(upstream, "REPO_ROOT", tmp_path)

    with pytest.MonkeyPatch.context() as fork_scope:
        _apply_fork_scope(fork_scope)
        scanned = {rel.as_posix() for rel, _path in upstream._iter_source_files()}
    assert scanned == {"some_package/reader.py"}

    scanned = {rel.as_posix() for rel, _path in upstream._iter_source_files()}
    assert scanned == {
        "some_package/reader.py",
        ".claude/worktrees/wave-2/gateway/config.py",
        "venv-ci/lib/vendored.py",
    }
