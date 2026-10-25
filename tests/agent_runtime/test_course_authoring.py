"""Course authoring (plan ``realm-course-subject-authoring-2026-10-21.md`` C1–C2) against a LOCAL bare remote.

Real git, a bare repository on disk as the course's remote (never a network clone or push), and a spy on
``git_cmd.run_git`` through the verbs' ``run=`` seam so a test can read every argv and its ``-c`` pairs.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_runtime import course_authoring, paths
from agent_runtime.course_authoring import CourseRefusal, CourseRefused
from agent_runtime.git_cmd import run_git
from agent_runtime.realm_membership import RealmSyncCredential

SECRET = "Basic x-access-token:ghs_COURSE_SECRET_7731"
COURSE = "crs_42"


def _git(*args: str, cwd: Path | None = None) -> str:
    done = subprocess.run(["git", "-c", "user.name=seed", "-c", "user.email=seed@test.invalid",
                           "-c", "commit.gpgsign=false", *args], cwd=cwd, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture
def remote(tmp_path) -> Path:
    """A bare course repo with one commit on ``main`` (its HEAD)."""

    bare = tmp_path / "remote" / "course.git"
    _git("init", "-q", "--bare", str(bare))
    _git("symbolic-ref", "HEAD", "refs/heads/main", cwd=bare)
    seed = tmp_path / "seed"
    _git("init", "-q", str(seed))
    _git("symbolic-ref", "HEAD", "refs/heads/main", cwd=seed)
    (seed / "README.md").write_text("# course\n", encoding="utf-8")
    (seed / "lessons").mkdir()
    (seed / "lessons" / "01.md").write_text("one\n", encoding="utf-8")
    _git("add", "-A", cwd=seed)
    _git("commit", "-q", "-m", "seed", cwd=seed)
    _git("push", "-q", str(bare), "main", cwd=seed)
    return bare


def _credential(git_url: str, realm_id: str = f"course:{COURSE}") -> RealmSyncCredential:
    return RealmSyncCredential.parse({
        "schema_version": 1,
        "realm_id": realm_id,
        "api_base": "https://api.test.invalid/api",
        "api_token": "etk_course_bearer",
        "git_url": git_url,
        "git_authorization": SECRET,
        "expires_at": "2999-01-01T00:00:00Z",
    })


class Spy:
    """``run_git`` passing through, recording ``(args, config)`` per call."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], tuple[str, ...]]] = []

    def __call__(self, args, *, repo=None, config=None, **kwargs):
        self.calls.append((list(args), tuple(config or ())))
        return run_git(args, repo=repo, config=config, **kwargs)

    def named(self, verb: str) -> list[tuple[list[str], tuple[str, ...]]]:
        return [call for call in self.calls if call[0][:1] == [verb]]


def _url(bare: Path) -> str:
    return bare.as_posix()


# ── C1: checkout ─────────────────────────────────────────────────────────────


def test_a_course_credential_clones_into_the_course_dir_with_the_header_on_the_network_calls(remote):
    spy = Spy()
    receipt = course_authoring.checkout(_credential(_url(remote)), run=spy)

    assert receipt.course == COURSE
    assert receipt.outcome == "added_fetched"
    assert receipt.branch == "main"
    assert receipt.path == paths.course_checkout_dir(COURSE)
    assert receipt.path == paths.store_root() / "courses" / COURSE / "repo"
    assert (receipt.path / "lessons" / "01.md").read_text(encoding="utf-8") == "one\n"
    header = f"http.extraHeader=Authorization: {SECRET}"
    for verb in ("ls-remote", "fetch"):
        assert spy.named(verb), f"no {verb} call"
        assert all(header in config for _args, config in spy.named(verb)), verb
    writes = [args for args, _config in spy.named("config") if "--get" not in args]
    assert not any(SECRET in " ".join(args) for args in writes)
    assert SECRET not in (receipt.path / ".git" / "config").read_text(encoding="utf-8")


def test_a_second_checkout_is_already_and_fast_forwards_the_clone(remote, tmp_path):
    credential = _credential(_url(remote))
    course_authoring.checkout(credential)
    other = tmp_path / "other"
    _git("clone", "-q", str(remote), str(other))
    (other / "lessons" / "02.md").write_text("two\n", encoding="utf-8")
    _git("add", "-A", cwd=other)
    _git("commit", "-q", "-m", "two", cwd=other)
    _git("push", "-q", "origin", "main", cwd=other)

    receipt = course_authoring.checkout(credential)

    assert receipt.outcome == "already"
    assert (receipt.path / "lessons" / "02.md").is_file()
    assert receipt.head == _git("rev-parse", "main", cwd=remote)


@pytest.mark.parametrize("realm_id", ["local:realm_7", "realm_server_9"])
def test_a_realm_credential_refuses_subject_mismatch_and_runs_no_git(remote, realm_id):
    spy = Spy()
    with pytest.raises(CourseRefused) as caught:
        course_authoring.checkout(_credential(_url(remote), realm_id=realm_id), run=spy)
    assert caught.value.reason is CourseRefusal.SUBJECT_MISMATCH
    assert spy.calls == []


def test_an_expired_credential_refuses_and_runs_no_git(remote):
    spy = Spy()
    expired = dataclasses.replace(_credential(_url(remote)), expires_at=datetime(2000, 1, 1, tzinfo=UTC))
    with pytest.raises(CourseRefused) as caught:
        course_authoring.checkout(expired, run=spy)
    assert caught.value.reason is CourseRefusal.CREDENTIAL_EXPIRED
    assert spy.calls == []


def test_an_expired_inline_credential_parses_to_course_credential_expired():
    raw = {"schema_version": 1, "realm_id": f"course:{COURSE}", "api_base": "https://a.invalid", "api_token": "t",
           "git_url": "https://github.com/o/r.git", "git_authorization": SECRET, "expires_at": "2000-01-01T00:00:00Z"}
    with pytest.raises(CourseRefused) as caught:
        course_authoring.parse_credential(raw)
    assert caught.value.reason is CourseRefusal.CREDENTIAL_EXPIRED
    with pytest.raises(CourseRefused) as caught:
        course_authoring.parse_credential({**raw, "git_url": ""})
    assert caught.value.reason is CourseRefusal.CREDENTIAL_INVALID


def test_a_clone_of_another_repo_refuses_url_mismatch(remote, tmp_path):
    course_authoring.checkout(_credential(_url(remote)))
    elsewhere = tmp_path / "remote" / "elsewhere.git"
    _git("clone", "-q", "--bare", str(remote), str(elsewhere))
    with pytest.raises(CourseRefused) as caught:
        course_authoring.checkout(_credential(_url(elsewhere)))
    assert caught.value.reason is CourseRefusal.URL_MISMATCH


def test_the_course_tree_is_outside_the_read_model_fingerprint():
    from agent_runtime import core_cache

    assert paths.COURSES_DIRNAME in core_cache._EXCLUDED_STORE_ENTRIES


# ── the method lane ──────────────────────────────────────────────────────────


def _rpc(method: str, params: dict) -> dict:
    from agent_runtime.serve_rpc import handle_request

    return handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def _raw(git_url: str, realm_id: str = f"course:{COURSE}") -> dict:
    return {"schema_version": 1, "realm_id": realm_id, "api_base": "https://api.test.invalid/api",
            "api_token": "etk_course_bearer", "git_url": git_url, "git_authorization": SECRET,
            "expires_at": "2999-01-01T00:00:00Z"}


def test_runtime_course_checkout_answers_the_receipt(remote):
    reply = _rpc("runtime.course.checkout", {"credential": _raw(_url(remote))})
    assert reply["result"]["course"] == COURSE
    assert reply["result"]["outcome"] == "added_fetched"


def test_runtime_course_checkout_refuses_a_realm_credential_by_reason(remote):
    reply = _rpc("runtime.course.checkout", {"credential": _raw(_url(remote), realm_id="local:r1")})
    assert reply["error"]["data"]["reason"] == "credential_subject_mismatch"
    reply = _rpc("runtime.course.checkout", {})
    assert reply["error"]["data"]["reason"] == "invalid_request"


def test_the_credential_reaches_no_receipt_log_reply_or_store_file(remote, caplog, tmp_path):
    caplog.set_level(logging.DEBUG)
    replies = [_rpc("runtime.course.checkout", {"credential": _raw(_url(remote))}),
               _rpc("runtime.course.checkout", {"credential": _raw(_url(tmp_path / "missing.git"))})]
    replies += _secret_free_extra_calls(remote)

    assert any(record.getMessage().startswith("{") and "course." in record.getMessage()
               for record in caplog.records), "no course receipt was logged"
    assert SECRET not in caplog.text
    assert "ghs_COURSE_SECRET" not in caplog.text
    assert "ghs_COURSE_SECRET" not in json.dumps(replies)
    leaked = [path for path in paths.store_root().rglob("*")
              if path.is_file() and b"ghs_COURSE_SECRET" in path.read_bytes()]
    assert leaked == []


def _secret_free_extra_calls(remote: Path) -> list[dict]:
    """The C2 verb's calls, a success and a refusal (the same secret grep covers them)."""

    params = {"credential": _raw(_url(remote)), "persona_id": "p_ada", "persona_name": "Ada", "branch": "intro",
              "message": "Add intro", "files": {"lessons/intro.md": "hello\n"}}
    return [_rpc("runtime.course.commit", params),
            _rpc("runtime.course.commit", {**params, "files": {"../escape.md": "x"}})]


# ── C2: commit ───────────────────────────────────────────────────────────────


def _commit(credential, run=run_git, **overrides):
    kwargs = {"persona_id": "p_ada", "persona_name": "Ada Lovelace", "branch": "intro", "message": "Add intro",
              "files": {"lessons/intro.md": "hello\n"}, "run": run, **overrides}
    return course_authoring.commit(credential, **kwargs)


def test_a_commit_lands_on_the_persona_branch_authored_by_the_persona_and_pushed(remote):
    credential = _credential(_url(remote))
    course_authoring.checkout(credential)
    spy = Spy()

    receipt = _commit(credential, run=spy, files={"lessons/intro.md": "hello\n", "lessons/deep/x.md": "x\n"},
                      deletes=["lessons/01.md"])

    branch = "agent/p_ada/intro"
    assert receipt.branch == branch
    assert receipt.files == ("lessons/01.md", "lessons/deep/x.md", "lessons/intro.md")
    worktree = paths.course_worktrees_dir(COURSE) / paths.safe_path_token(branch)
    assert (worktree / "lessons" / "intro.md").read_text(encoding="utf-8") == "hello\n"
    assert not (worktree / "lessons" / "01.md").exists()
    assert _git("rev-list", "--count", f"main..{branch}", cwd=remote) == "1"
    assert _git("rev-parse", branch, cwd=remote) == receipt.sha
    assert _git("log", "-1", "--format=%an <%ae>", branch, cwd=remote) == "Ada Lovelace <p_ada@eternia.agents>"
    pushes = [args for args, _config in spy.named("push")]
    assert pushes == [["push", "-u", "origin", branch]]
    assert all(f"http.extraHeader=Authorization: {SECRET}" in config for _args, config in spy.named("push"))
    assert not any(flag in args for args, _config in spy.calls for flag in ("--force", "-f", "--force-with-lease"))
    assert _git("rev-parse", "main", cwd=remote) != receipt.sha  # the default branch never moves


def test_a_second_commit_continues_the_branch(remote):
    credential = _credential(_url(remote))
    course_authoring.checkout(credential)
    first = _commit(credential)
    second = _commit(credential, files={"lessons/intro.md": "hello again\n"}, message="Revise intro")
    assert _git("rev-parse", f"{second.sha}^", cwd=remote) == first.sha
    assert _git("rev-parse", "agent/p_ada/intro", cwd=remote) == second.sha


@pytest.mark.parametrize("bad", ["../x.md", "lessons/../../x.md", "/etc/x", "C:/x", ".git/config"])
def test_a_path_leaving_the_repo_refuses(remote, bad):
    credential = _credential(_url(remote))
    course_authoring.checkout(credential)
    with pytest.raises(CourseRefused) as caught:
        _commit(credential, files={bad: "x"})
    assert caught.value.reason is CourseRefusal.PATH_INVALID
    assert not (paths.course_worktrees_dir(COURSE).parent / "x.md").exists()


def test_a_diverged_pushed_branch_refuses_and_never_forces(remote, tmp_path):
    credential = _credential(_url(remote))
    course_authoring.checkout(credential)
    _commit(credential)
    rival = tmp_path / "rival"
    _git("clone", "-q", str(remote), str(rival))
    _git("checkout", "-q", "-b", "agent/p_ada/intro", "origin/main", cwd=rival)
    (rival / "rival.md").write_text("rival\n", encoding="utf-8")
    _git("add", "-A", cwd=rival)
    _git("commit", "-q", "-m", "rival", cwd=rival)
    _git("push", "-q", "--force", "origin", "agent/p_ada/intro", cwd=rival)  # the test's own git, not the verb's
    spy = Spy()

    with pytest.raises(CourseRefused) as caught:
        _commit(credential, run=spy, files={"lessons/intro.md": "mine\n"})

    assert caught.value.reason is CourseRefusal.BRANCH_DIVERGED
    assert not any(flag in args for args, _config in spy.calls for flag in ("--force", "-f", "--force-with-lease"))
    assert _git("log", "-1", "--format=%s", "agent/p_ada/intro", cwd=remote) == "rival"


def test_a_rejected_push_is_course_branch_diverged(remote):
    credential = _credential(_url(remote))
    course_authoring.checkout(credential)

    def rejecting(args, **kwargs):
        if list(args[:1]) == ["push"]:
            return subprocess.CompletedProcess(args, 1, "", " ! [rejected] agent/p_ada/intro (non-fast-forward)\n")
        return run_git(args, **kwargs)

    with pytest.raises(CourseRefused) as caught:
        _commit(credential, run=rejecting)
    assert caught.value.reason is CourseRefusal.BRANCH_DIVERGED


def test_commit_before_checkout_refuses_not_checked_out(remote):
    with pytest.raises(CourseRefused) as caught:
        _commit(_credential(_url(remote)))
    assert caught.value.reason is CourseRefusal.NOT_CHECKED_OUT


def test_commit_refuses_a_realm_credential_and_an_unchanged_tree(remote):
    with pytest.raises(CourseRefused) as caught:
        _commit(_credential(_url(remote), realm_id="local:r1"))
    assert caught.value.reason is CourseRefusal.SUBJECT_MISMATCH
    credential = _credential(_url(remote))
    clone = course_authoring.checkout(credential).path
    same = (clone / "README.md").read_bytes().decode("utf-8")  # the bytes git checked out, EOLs and all
    with pytest.raises(CourseRefused) as caught:
        _commit(credential, files={"README.md": same})
    assert caught.value.reason is CourseRefusal.NOTHING_TO_COMMIT


def test_runtime_course_commit_answers_the_receipt_and_refuses_by_reason(remote):
    raw = _raw(_url(remote))
    _rpc("runtime.course.checkout", {"credential": raw})
    params = {"credential": raw, "persona_id": "p_ada", "branch": "intro", "message": "Add intro",
              "files": {"lessons/intro.md": "hello\n"}}
    reply = _rpc("runtime.course.commit", params)
    assert reply["result"]["branch"] == "agent/p_ada/intro"
    assert reply["result"]["files"] == ["lessons/intro.md"]
    assert _git("log", "-1", "--format=%an", "agent/p_ada/intro", cwd=remote) == "p_ada"
    refused = _rpc("runtime.course.commit", {**params, "files": {"../x.md": "x"}})
    assert refused["error"]["data"]["reason"] == "course_path_invalid"
    refused = _rpc("runtime.course.commit", {**params, "files": ["not", "a", "map"]})
    assert refused["error"]["data"]["reason"] == "invalid_request"


# ── C3: pull request ─────────────────────────────────────────────────────────

GITHUB_URL = "https://github.com/eternia-courses/crs-42.git"


class FakeGitHub:
    """``git_host_account.github_request``'s shape; records every call, answers from ``open`` / ``status``."""

    def __init__(self, *, open_prs=(), post_status=201, get_status=200) -> None:
        self.calls: list[tuple[str, str, str, dict | None]] = []
        self.open_prs, self.post_status, self.get_status = list(open_prs), post_status, get_status

    def __call__(self, method, path, authorization, body=None, **_kwargs):
        self.calls.append((method, path, authorization, body))
        if method == "GET":
            return self.get_status, self.open_prs if self.get_status == 200 else {"message": "no"}
        if self.post_status == 201:
            return 201, {"number": 7, "html_url": "https://github.com/eternia-courses/crs-42/pull/7"}
        return self.post_status, {"message": "Resource not accessible by integration"}

    def posts(self) -> list[tuple[str, str, str, dict | None]]:
        return [call for call in self.calls if call[0] == "POST"]


def _pr(credential, github, **over):
    params = {"persona_id": "p_ada", "branch": "intro", "title": "Add the intro", "body": "Why: …",
              "base": "main", "request": github, **over}
    return course_authoring.pull_request(credential, **params)


def test_a_pull_request_posts_head_and_base_with_the_credential_as_authorization():
    github = FakeGitHub()
    receipt = _pr(_credential(GITHUB_URL), github)

    assert (receipt.number, receipt.existing, receipt.branch) == (7, False, "agent/p_ada/intro")
    lookup, post = github.calls
    assert lookup[:2] == ("GET", "/repos/eternia-courses/crs-42/pulls?state=open&head=eternia-courses:agent/p_ada/intro")
    assert post[:2] == ("POST", "/repos/eternia-courses/crs-42/pulls")
    assert post[3] == {"title": "Add the intro", "head": "agent/p_ada/intro", "base": "main", "body": "Why: …"}
    assert {call[2] for call in github.calls} == {SECRET}
    assert SECRET not in repr(receipt)


def test_an_open_pull_request_for_the_branch_is_answered_without_a_post():
    github = FakeGitHub(open_prs=[{"number": 3, "html_url": "https://github.com/eternia-courses/crs-42/pull/3"}])
    receipt = _pr(_credential(GITHUB_URL), github)

    assert (receipt.number, receipt.existing) == (3, True)
    assert github.posts() == []
    # Positive control: the same call with no open PR does post.
    assert _pr(_credential(GITHUB_URL), FakeGitHub()).existing is False


@pytest.mark.parametrize("status", [403, 404])
def test_github_refusing_the_app_is_pull_request_not_permitted(status):
    with pytest.raises(CourseRefused) as caught:
        _pr(_credential(GITHUB_URL), FakeGitHub(post_status=status))
    assert caught.value.reason is CourseRefusal.PR_NOT_PERMITTED
    assert SECRET not in str(caught.value)


def test_a_pull_request_refuses_another_host_and_another_subject_before_any_request(remote):
    github = FakeGitHub()
    with pytest.raises(CourseRefused) as caught:
        _pr(_credential(_url(remote)), github)
    assert caught.value.reason is CourseRefusal.HOST_UNSUPPORTED
    with pytest.raises(CourseRefused) as caught:
        _pr(_credential(GITHUB_URL, realm_id="local:r1"), github)
    assert caught.value.reason is CourseRefusal.SUBJECT_MISMATCH
    assert github.calls == []


def test_the_base_defaults_to_the_checked_out_default_branch(remote):
    course_authoring.checkout(_credential(_url(remote)))
    github = FakeGitHub()
    _pr(_credential(GITHUB_URL), github, base=None)
    assert github.posts()[0][3]["base"] == "main"


def test_runtime_course_pull_request_answers_the_receipt_and_refuses_by_reason(monkeypatch):
    from agent_runtime import git_host_account

    github = FakeGitHub()
    monkeypatch.setattr(git_host_account, "github_request", github)
    course_authoring.paths.course_checkout_dir(COURSE)  # no clone: base must come from a checkout
    params = {"credential": _raw(GITHUB_URL), "persona_id": "p_ada", "branch": "intro", "title": "Add the intro"}
    refused = _rpc("runtime.course.pull_request", params)
    assert refused["error"]["data"]["reason"] == "course_not_checked_out"
    monkeypatch.setattr(course_authoring, "_origin_head", lambda _git, _repo: "main")
    (course_authoring.paths.course_checkout_dir(COURSE) / ".git").mkdir(parents=True)
    reply = _rpc("runtime.course.pull_request", params)
    assert reply["result"] == {"course": COURSE, "branch": "agent/p_ada/intro", "number": 7,
                               "html_url": "https://github.com/eternia-courses/crs-42/pull/7", "existing": False}
    github.post_status = 403
    refused = _rpc("runtime.course.pull_request", {**params, "branch": "other"})
    assert refused["error"]["data"]["reason"] == "pull_request_not_permitted"
    assert SECRET not in json.dumps(refused)
