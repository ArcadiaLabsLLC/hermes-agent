"""RT-SELF-REPO-GUARD-VAR-AND-GITDIR-TARGETS: a ``$VAR`` / ``${VAR}`` in a ``cd`` / ``-C`` /
``--work-tree`` target is expanded the way the shell will before the self-repo guard judges it.

Before the fix the literal word ``$TMPDIR/lr`` was resolved against the session cwd, so git aimed
at a scratch clone from inside the live checkout was refused as rewriting the checkout, and the
refusal named the checkout rather than the unexpanded word. Every allow below has a twin with one
variable changed that must still block (the positive control), so an allow cannot pass because
the guard never reached the command.
"""

import subprocess
from pathlib import Path

import pytest

from tools.self_repo_guard import detect_self_repo_git_mutation
from tools.self_repo_guard_vars import UNRESOLVED_ROOT, expand_target, is_unresolved


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "hermes-agent"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root.resolve()


@pytest.fixture
def scratch(tmp_path):
    other = tmp_path / "scratch" / "lr"
    other.mkdir(parents=True)
    return other.resolve()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("GUARD_UNSET", raising=False)


def _detect(command, cwd, root):
    return detect_self_repo_git_mutation(command, str(cwd), source_root=root)


@pytest.mark.parametrize("spelling", ['git -C "$GUARD_DIR" checkout x', 'git -C "${GUARD_DIR}" checkout x',
                                      'git -C $GUARD_DIR/. reset --hard', 'cd "$GUARD_DIR" && git checkout x',
                                      'git --work-tree="$GUARD_DIR" checkout x'])
def test_environment_variable_target_is_expanded(repo, scratch, monkeypatch, spelling):
    monkeypatch.setenv("GUARD_DIR", scratch.as_posix())
    assert _detect(spelling, repo, repo) == (False, None)
    monkeypatch.setenv("GUARD_DIR", repo.as_posix())  # positive control: the same word, aimed at the checkout
    hit, message = _detect(spelling, repo, repo)
    assert hit is True and "live source checkout" in message


@pytest.mark.parametrize("assign", ["GUARD_LR={dir}; ", "export GUARD_LR={dir} && ", "GUARD_A={dir}; GUARD_LR=\"$GUARD_A\"; "])
def test_variable_assigned_by_an_earlier_statement_is_expanded(repo, scratch, assign):
    command = assign.format(dir=scratch.as_posix()) + 'git -C "$GUARD_LR" checkout x'
    assert _detect(command, repo, repo) == (False, None)
    hit, message = _detect(assign.format(dir=repo.as_posix()) + 'git -C "$GUARD_LR" checkout x', repo, repo)
    assert hit is True and "live source checkout" in message


def test_same_statement_prefix_does_not_expand_its_own_arguments(repo, scratch):
    # bash expands "$GUARD_LR" before the prefix assignment takes effect: git really runs in the cwd.
    hit, message = _detect(f'GUARD_LR={scratch.as_posix()} git -C "$GUARD_LR" checkout x', repo, repo)
    assert hit is True and "`$GUARD_LR`" in message


def test_subshell_assignment_does_not_leak(repo, scratch):
    hit, message = _detect(f'(GUARD_LR={scratch.as_posix()}); git -C "$GUARD_LR" checkout x', repo, repo)
    assert hit is True and "`$GUARD_LR`" in message
    assert _detect(f'GUARD_LR={scratch.as_posix()}; git -C "$GUARD_LR" checkout x', repo, repo) == (False, None)


@pytest.mark.parametrize("target", ['"$GUARD_UNSET/lr"', '"${GUARD_UNSET}/lr"', '"/x/$GUARD_UNSET"', '"C:/x/$GUARD_UNSET"'])
def test_unresolved_target_is_refused_naming_the_word(repo, tmp_path, target):
    hit, message = _detect(f"git -C {target} checkout x", tmp_path, repo)  # cwd OUTSIDE the checkout
    assert hit is True
    assert "GUARD_UNSET" in message and "not set" in message
    assert "would rewrite" not in message


def test_unresolved_target_read_only_command_passes(repo):
    assert _detect('git -C "$GUARD_UNSET/lr" status', repo, repo) == (False, None)
    assert _detect('git -C "$GUARD_UNSET/lr" checkout x', repo, repo)[0] is True  # positive control


def test_git_dir_without_work_tree_still_judges_the_cwd(repo, scratch, monkeypatch):
    monkeypatch.setenv("GUARD_DIR", scratch.as_posix())
    hit, message = _detect('git --git-dir="$GUARD_DIR/.git" merge y', repo, repo)
    assert hit is True and "live source checkout" in message
    assert _detect('git --git-dir="$GUARD_DIR/.git" merge y', scratch, repo) == (False, None)


def test_expand_target_never_escapes_the_unresolved_root():
    for word in ("$GUARD_UNSET", "/abs/$GUARD_UNSET", "C:/abs/$GUARD_UNSET", r"C:\abs\$GUARD_UNSET"):
        assert is_unresolved(Path(expand_target(word, {}))), word
    assert expand_target("plain/path", {}) == "plain/path"
    assert not is_unresolved(UNRESOLVED_ROOT.parent)
