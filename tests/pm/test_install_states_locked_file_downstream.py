"""A file a live process holds does not stop the orphan reclaim at that state (``pm/install_states.py``).

On Windows a hardlinked ``.pyd`` that any running Python maps cannot be unlinked through ANY of
its links (``[WinError 5]``, 335/335 orphan states on 2026-10-18). The reclaim must leave that
state, record intact, for the next pass, and go on to the next orphan.
"""

from __future__ import annotations

import pytest

from pm.install_states import collect_orphan_install_states, orphan_install_states


def _state(installs, key, project_root):
    state = installs / key
    (state / "inputs").mkdir(parents=True)
    (state / "inputs" / ".project-root").write_text(str(project_root), encoding="utf-8")
    (state / "environments" / "gen" / "venv").mkdir(parents=True)
    return state


@pytest.mark.platforms("windows")
def test_a_held_file_skips_its_state_and_the_reclaim_goes_on(tmp_path):
    installs = tmp_path / "installs"
    stuck = _state(installs, "aaaa", tmp_path / "gone-a")
    clean = _state(installs, "bbbb", tmp_path / "gone-b")
    pyd = stuck / "environments" / "gen" / "venv" / "mask.cp314-win_amd64.pyd"
    pyd.write_bytes(b"\0")
    held = open(pyd, "rb")  # no FILE_SHARE_DELETE: the unlink fails as a mapped DLL's does
    try:
        assert collect_orphan_install_states(installs) == [clean]
        assert not clean.exists()
        assert pyd.is_file() and (stuck / "inputs" / ".project-root").is_file()
        assert orphan_install_states(installs) == [stuck]
    finally:
        held.close()
    assert collect_orphan_install_states(installs) == [stuck] and not stuck.exists()
