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
                           "-c", "commit.gpgsign=false", *args], cwd=cwd, capture_output=True, text=True)
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
    """The C2 verbs append their calls here (the same secret grep covers them)."""

    return []
