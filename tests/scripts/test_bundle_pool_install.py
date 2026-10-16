"""The bundle pool install: outside the work tree, bounded retry on a sharing violation only."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.bundles.pool_install import install_pool, is_sharing_violation

HELD = ("error: Failed to install: pillow_heif-1.6.0-cp314-cp314-win_amd64.whl\n"
        "  Caused by: failed to remove directory `x\\pillow_heif-1.6.0.data`: The process cannot "
        "access the file because it is being used by another process. (os error 32)\n")


class FakeUv:
    """Each call writes a marker into its --target, then answers the next scripted result."""

    def __init__(self, results):
        self.results = list(results)
        self.targets: list[Path] = []

    def __call__(self, cmd, **kwargs):
        target = Path(cmd[-1])
        self.targets.append(target)
        assert not any(target.iterdir()), "every attempt starts from an empty folder"
        (target / "pkg.py").write_text("x", encoding="utf-8")
        code, err = self.results.pop(0)
        return subprocess.CompletedProcess(cmd, code, "", err)


def _install(tmp_path: Path, uv: FakeUv, sleeps: list[float]) -> Path:
    stage = tmp_path / "work" / "core.pool"
    install_pool(lambda into: ["uv", "pip", "install", "--target", str(into)], stage, cwd=tmp_path, run=uv,
                 scratch_parent=tmp_path / "scratch", delays=(2.0, 5.0), sleep=sleeps.append)
    return stage


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    (tmp_path / "scratch").mkdir()
    return tmp_path / "scratch"


def test_a_sharing_violation_is_retried_from_an_empty_folder_and_the_pool_lands(tmp_path, scratch):
    uv, sleeps = FakeUv([(2, HELD), (0, "")]), []
    stage = _install(tmp_path, uv, sleeps)
    assert sleeps == [2.0]
    assert len(uv.targets) == 2 and uv.targets[0] != uv.targets[1]
    assert (stage / "pkg.py").is_file()
    assert list(scratch.iterdir()) == [], "no scratch folder is left behind"


def test_uv_never_installs_into_the_work_tree(tmp_path):
    stage, uv = tmp_path / "work" / "core.pool", FakeUv([(0, "")])
    install_pool(lambda into: ["uv", "--target", str(into)], stage, cwd=tmp_path, run=uv, sleep=lambda _: None)
    assert not uv.targets[0].is_relative_to(stage.parent)
    assert (stage / "pkg.py").is_file() and not uv.targets[0].exists()


def test_another_failure_is_not_retried(tmp_path, scratch):
    uv, sleeps = FakeUv([(2, "error: hash mismatch"), (0, "")]), []
    with pytest.raises(subprocess.CalledProcessError):
        _install(tmp_path, uv, sleeps)
    assert sleeps == [] and len(uv.targets) == 1


def test_the_retry_is_bounded(tmp_path, scratch):
    uv, sleeps = FakeUv([(2, HELD)] * 3), []
    with pytest.raises(subprocess.CalledProcessError):
        _install(tmp_path, uv, sleeps)
    assert sleeps == [2.0, 5.0] and len(uv.targets) == 3


def test_a_previous_pool_is_replaced_not_merged(tmp_path, scratch):
    stage = tmp_path / "work" / "core.pool"
    stage.mkdir(parents=True)
    (stage / "stale.py").write_text("old", encoding="utf-8")
    _install(tmp_path, FakeUv([(0, "")]), [])
    assert sorted(p.name for p in stage.iterdir()) == ["pkg.py"]


def test_the_measured_uv_message_is_a_sharing_violation():
    assert is_sharing_violation(HELD)
    assert not is_sharing_violation("error: hash mismatch for pillow-heif")
