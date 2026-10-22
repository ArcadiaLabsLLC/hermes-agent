"""RT-SELF-REPO-GUARD-WINDOWS-PATHS: the self-repo git guard reads a ``cd`` / ``-C`` target
spelled with backslashes or the Git-Bash ``/<drive>/…`` form the way the shell that runs it will.

Before the fix every backslash or Git-Bash target was lost (the word deobfuscation dropped the
backslashes; ``/x/…`` resolved to ``<cwd drive>:\\x\\…``), so the command was judged against the
session's cwd — git in ANOTHER repo was refused as rewriting the live checkout, and git aimed AT
the live checkout from elsewhere through a backslash ``cd`` passed. Each shape below is pinned
with its forward-slash twin as the positive control.
"""

import os
import subprocess

import pytest

from tools.path_identity import shell_path_operand
from tools.self_repo_guard import detect_self_repo_git_mutation

pytestmark = pytest.mark.skipif(os.name != "nt", reason="drive-letter and Git-Bash spellings are Windows shapes")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "hermes-agent"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root.resolve()


@pytest.fixture
def other(tmp_path):
    path = tmp_path / "Unreal Engine" / "EterniaLauncher"
    path.mkdir(parents=True)
    return path.resolve()


def _blocked(command, cwd, root):
    return detect_self_repo_git_mutation(command, str(cwd), source_root=root)[0]


def _msys(path):
    drive, rest = path.as_posix().split(":", 1)
    return f"/{drive.lower()}{rest}"


_OTHER_REPO_SHAPES = [
    'cd "{back}" && git merge --ff-only origin/main',
    'cd "{back}"; git merge --ff-only origin/main',
    'cd "{back}"\ngit merge --ff-only origin/main',
    "cd '{back}' && git rebase origin/main",
    'git -C "{back}" merge --ff-only origin/main',
    'git --work-tree="{back}" merge origin/main',
    'cd "{fwd}" && git merge --ff-only origin/main',
    'git -C "{fwd}" merge --ff-only origin/main',
    'cd "{msys}" && git rebase origin/main',
    'git -C "{msys}" rebase origin/main',
]


@pytest.mark.parametrize("shape", _OTHER_REPO_SHAPES)
def test_git_in_another_repo_is_not_judged_against_the_live_checkout(repo, other, shape):
    command = shape.format(back=str(other), fwd=other.as_posix(), msys=_msys(other))
    assert _blocked(command, repo, repo) is False


@pytest.mark.parametrize("shape", [
    'cd "{back}" && git merge origin/main',
    'cd "{back}"; git checkout main',
    "cd '{back}' && git rebase origin/main",
    'git -C "{back}" merge origin/main',
    'git --work-tree="{back}" merge origin/main',
    'cd "{fwd}" && git merge origin/main',
    'git -C "{fwd}" merge origin/main',
    'cd {msys} && git rebase origin/main',
    'git -C {msys} pull',
])
def test_git_aimed_at_the_live_checkout_is_blocked_in_every_spelling(repo, other, shape):
    command = shape.format(back=str(repo), fwd=repo.as_posix(), msys=_msys(repo))
    assert _blocked(command, other, repo) is True


def test_git_in_the_live_checkout_cwd_is_still_blocked(repo):
    assert _blocked("git merge origin/main", repo, repo) is True


def test_a_backslash_git_executable_is_still_git(repo):
    assert _blocked('"C:\\Program Files\\Git\\cmd\\git.exe" merge origin/main', repo, repo) is True


@pytest.mark.parametrize("word, expected", [
    ('"X:\\Unreal Engine\\Launcher"', "X:/Unreal Engine/Launcher"),
    ("'X:\\a\\b'", "X:/a/b"),
    ('"X:/a/b"', "X:/a/b"),
    ("/x/Unreal/wt", "X:/Unreal/wt"),
    ('--work-tree="X:\\a"', "--work-tree=X:/a"),
    ("X:\\a", None),  # unquoted: the shell itself eats the backslash -> `X:a`
    ('"$TMPDIR/lr"', None),
    ("origin/main", None),
])
def test_shell_path_operand_spells_the_path_the_shell_hands_over(word, expected):
    assert shell_path_operand(word) == expected
