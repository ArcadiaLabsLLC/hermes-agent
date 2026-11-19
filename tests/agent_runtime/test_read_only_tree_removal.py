"""The fork's removals of a tree that holds git's read-only objects go through upstream's ``utils.rmtree_readonly``.

Three fork modules carried their own chmod-and-retry handler (RT-READ-ONLY-TREE-REMOVAL-COPIED-THREE-TIMES);
theirs cleared the bit on the failing file only, so a read-only objects FOLDER (a POSIX unlink needs a
writable parent) still stopped the removal. Upstream's helper clears the parent too and is tested in
``tests/test_utils_rmtree_readonly.py``; these pin that each fork caller uses it.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest


def _clone_with_read_only_objects(root: Path) -> Path:
    objects = root / ".git" / "objects" / "4b"
    objects.mkdir(parents=True)
    (objects / "825dc642cb6eb9a060e54bf8d69288fbee4904").write_bytes(b"blob")
    (objects / "825dc642cb6eb9a060e54bf8d69288fbee4904").chmod(stat.S_IREAD)
    objects.chmod(0o555)
    return root


@pytest.fixture
def clone(tmp_path):
    root = _clone_with_read_only_objects(tmp_path / "clone")
    yield root
    if root.exists():  # a red leaves the read-only folder; give tmp_path its cleanup back
        (root / ".git" / "objects" / "4b").chmod(0o755)


def test_leaving_a_realm_removes_its_clone_with_read_only_objects(clone):
    """Mutation: ``shutil.rmtree`` back in place of ``rmtree_readonly`` in ``realm_leave`` -> the clone stays
    (``_drop_clone`` falls back to dropping its remotes), red."""
    from agent_runtime import realm_leave

    realm_leave._drop_clone(clone)

    assert not clone.exists()


def test_removing_a_namespace_entry_removes_read_only_objects(clone):
    """Mutation: ``shutil.rmtree`` back in place of ``rmtree_readonly`` in ``namespace_admin._rm`` -> raises
    PermissionError, red."""
    from agent_runtime import namespace_admin

    namespace_admin._rm(clone)

    assert not clone.exists()
