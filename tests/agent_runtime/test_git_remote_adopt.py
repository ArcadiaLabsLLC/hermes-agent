"""The shared adopter (p10-work plan §2.3, stage R0): real ``git`` in ``tmp_path``, a bare ``origin.git``.

Nothing reaches a network: every remote is a local bare repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_runtime.git_remote_adopt import Adoption, AdoptRefused, adopt_remote

IDENTITY = ("user.name=Adopt Test", "user.email=adopt@test.local")


def _git(repo: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-c", IDENTITY[0], "-c", IDENTITY[1], "-C", str(repo), *args],
                          capture_output=True, text=True, check=False)
    if check and done.returncode:
        raise AssertionError(done.stderr)
    return done.stdout.strip()


def _bare(tmp_path: Path, name: str = "origin.git") -> Path:
    bare = tmp_path / name
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    return bare


def _repo(root: Path, files: dict[str, str] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for rel, text in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if files:
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "seed")
    return root


def _url(path: Path) -> str:
    return str(path)


def test_empty_remote_gets_the_local_history_pushed_with_upstream(tmp_path):
    bare = _bare(tmp_path)
    repo = _repo(tmp_path / "local", {"a.md": "a"})
    got = adopt_remote(repo, _url(bare))
    assert got.outcome is Adoption.ADDED_PUSHED and got.head == _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "rev-parse", "--abbrev-ref", "@{u}") == "origin/main"
    assert _git(bare, "rev-parse", "main") == got.head


def test_empty_local_takes_the_remote(tmp_path):
    bare = _bare(tmp_path)
    seed = _repo(tmp_path / "seed", {"b.md": "b"})
    adopt_remote(seed, _url(bare))
    fresh = _repo(tmp_path / "fresh")
    got = adopt_remote(fresh, _url(bare))
    assert got.outcome is Adoption.ADDED_FETCHED
    assert (fresh / "b.md").read_text(encoding="utf-8") == "b"
    assert _git(fresh, "rev-parse", "--abbrev-ref", "@{u}") == "origin/main"


def test_same_url_is_already_and_still_fetches(tmp_path):
    bare = _bare(tmp_path)
    repo = _repo(tmp_path / "local", {"a.md": "a"})
    adopt_remote(repo, _url(bare))
    other = _repo(tmp_path / "other")
    adopt_remote(other, _url(bare))
    (other / "c.md").write_text("c", encoding="utf-8")
    _git(other, "add", "-A")
    _git(other, "commit", "-q", "-m", "more")
    _git(other, "push", "-q", "origin", "HEAD:main")
    got = adopt_remote(repo, _url(bare))
    assert got.outcome is Adoption.ALREADY
    assert _git(repo, "rev-parse", "origin/main") == _git(other, "rev-parse", "HEAD")


def test_a_different_origin_refuses_url_mismatch(tmp_path):
    repo = _repo(tmp_path / "local", {"a.md": "a"})
    _git(repo, "remote", "add", "origin", _url(_bare(tmp_path, "elsewhere.git")))
    with pytest.raises(AdoptRefused) as refused:
        adopt_remote(repo, _url(_bare(tmp_path)))
    assert refused.value.reason == "url_mismatch"


@pytest.mark.parametrize(("theirs", "outcome"), [("realms/b/x.md", Adoption.MERGED_UNRELATED), ("README.md", None)])
def test_unrelated_histories_merge_only_when_paths_are_disjoint(tmp_path, theirs, outcome):
    bare = _bare(tmp_path)
    adopt_remote(_repo(tmp_path / "one", {theirs: "theirs", ".gitattributes": "* text=auto\n"}), _url(bare))
    mine = _repo(tmp_path / "two", {"realms/a/x.md": "mine", "README.md": "mine", ".gitattributes": "* -text\n"})
    if outcome is None:
        with pytest.raises(AdoptRefused) as refused:
            adopt_remote(mine, _url(bare), config=IDENTITY, merge_unrelated_if_disjoint=True)
        assert refused.value.reason == "remote_diverged" and "README.md" in refused.value.detail
        return
    got = adopt_remote(mine, _url(bare), config=IDENTITY, merge_unrelated_if_disjoint=True)
    assert got.outcome is outcome
    assert (mine / "realms/b/x.md").is_file() and (mine / "realms/a/x.md").is_file()
    assert (mine / ".gitattributes").read_text(encoding="utf-8") == "* -text\n"  # ours wins
    assert _git(mine, "rev-parse", "--abbrev-ref", "@{u}") == "origin/main"


def test_unrelated_histories_refuse_without_the_merge_flag(tmp_path):
    bare = _bare(tmp_path)
    adopt_remote(_repo(tmp_path / "one", {"realms/b/x.md": "b"}), _url(bare))
    with pytest.raises(AdoptRefused) as refused:
        adopt_remote(_repo(tmp_path / "two", {"realms/a/x.md": "a"}), _url(bare))
    assert refused.value.reason == "remote_diverged"


def test_config_pairs_never_land_in_git_config(tmp_path):
    bare = _bare(tmp_path)
    repo = _repo(tmp_path / "local", {"a.md": "a"})
    adopt_remote(repo, _url(bare), config=("http.extraHeader=Authorization: x-secret-header",))
    text = (repo / ".git" / "config").read_text(encoding="utf-8").lower()
    assert "extraheader" not in text and "x-secret-header" not in text


def test_stderr_is_scrubbed(tmp_path):
    repo = _repo(tmp_path / "local", {"a.md": "a"})
    missing = tmp_path / "no-such-remote-SECRETVALUE.git"
    with pytest.raises(AdoptRefused) as refused:
        adopt_remote(repo, str(missing), config=("http.extraHeader=SECRETVALUE",))
    assert refused.value.reason == "fetch_failed"
    assert "SECRETVALUE" not in refused.value.detail and "[redacted]" in refused.value.detail


def test_not_a_repo_refuses(tmp_path):
    (tmp_path / "plain").mkdir()
    with pytest.raises(AdoptRefused) as refused:
        adopt_remote(tmp_path / "plain", "https://example.invalid/x.git",
                     run=lambda args, **kw: subprocess.CompletedProcess(args, 128, "", "not a git repository"))
    assert refused.value.reason == "not_a_repo"
