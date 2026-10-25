"""The GitHub door the default brain's promotion uses (p10-work plan §2.4, stage A1).

"Connected" (owner decision §7, recommended path) means the machine's OWN git credential chain —
``hermes_cli.git_credentials.iter_git_basic_auth("https://github.com")``: ``GITHUB_TOKEN`` /
``GH_TOKEN``, ``gh auth token``, the git credential helper — holds a credential that
``GET https://api.github.com/user`` accepts. The Work writer and the batch lanes push through that
same chain and nothing else, so a remote made with any other credential would be one the writer
cannot reach. A refused credential yields to the next source (upstream's #115257 rule); a network
failure means "not connected now", never an error. The answer is memoised per process for
``CONNECTED_TTL_S`` (the ``github_api._gh_cli_token`` rule: never spawn ``gh`` per call); a network
failure is not memoised.

``create_private_repo`` makes ``eternia-work-<slug>`` PRIVATE with no initial commit; a name that
exists already refuses ``remote_exists`` and is never adopted. The token never reaches a log line,
a refusal or a ``repr``. Pinned by ``tests/agent_runtime/test_git_host_account.py``.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .work_store.reasons import Reason

__layer__ = "stores"
__all__ = [
    "CONNECTED_TTL_S",
    "GitHostRefused",
    "GitHubAccount",
    "connected_github",
    "create_private_repo",
    "reset_connected_cache",
]

API = "https://api.github.com"
GITHUB = "https://github.com"
CONNECTED_TTL_S = 600.0
_TIMEOUT_S = 10.0

logger = logging.getLogger(__name__)
#: The test seam: ``urllib.request.urlopen``'s shape.
urlopen = urllib.request.urlopen


@dataclass(frozen=True)
class GitHubAccount:
    login: str
    source: str
    _auth: tuple[str, str] = field(default=("", ""), repr=False, compare=False)

    def authorization(self) -> str:
        raw = f"{self._auth[0]}:{self._auth[1]}".encode()
        return "Basic " + base64.b64encode(raw).decode("ascii")


class GitHostRefused(ValueError):
    """A git-host refusal with its typed ``reason`` (a ``work_store.reasons.Reason``); never carries a token."""

    def __init__(self, reason: Reason, detail: str = "") -> None:
        super().__init__(detail or reason.value)
        self.reason = reason
        self.detail = detail


_cache: tuple[float, GitHubAccount | None] | None = None


def reset_connected_cache() -> None:
    global _cache
    _cache = None


def _github_user_agent() -> str:
    """An explicit UA (the realm module's rule: the stdlib default is bot-blocked at some edges)."""

    try:
        from hermes_cli import __version__ as version
    except Exception:  # a UA never breaks a call
        version = "unknown"
    return f"Hermes-Agent/{version} (work-brain)"


def _request(method: str, path: str, authorization: str, body: dict[str, Any] | None = None,
             *, timeout: float = _TIMEOUT_S) -> tuple[int, dict[str, Any]]:
    """``(status, json object)``: :func:`github_request` with a non-object body read as ``{}``."""

    status, payload = github_request(method, path, authorization, body, timeout=timeout)
    return status, payload if isinstance(payload, dict) else {}


def github_request(method: str, path: str, authorization: str, body: dict[str, Any] | None = None,
                   *, timeout: float = _TIMEOUT_S) -> tuple[int, Any]:
    """``(status, json body)`` — an object or a list, ``{}`` when the body is not JSON; an HTTP error status
    is returned, a network failure raises ``OSError``. The authorization is a header, never logged."""

    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": authorization, "Accept": "application/vnd.github+json", "User-Agent": _github_user_agent(),
        "X-GitHub-Api-Version": "2022-11-28", **({"Content-Type": "application/json"} if data else {})})
    try:
        with urlopen(request, timeout=timeout) as response:
            status, raw = int(getattr(response, "status", 200)), response.read()
    except urllib.error.HTTPError as error:
        status, raw = int(error.code), error.read() or b""
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        payload = {}
    return status, payload if isinstance(payload, (dict, list)) else {}


def connected_github(timeout: float = _TIMEOUT_S) -> GitHubAccount | None:
    """The first credential of the machine's chain that GitHub accepts, as an account; else None."""

    global _cache
    if _cache is not None and time.monotonic() - _cache[0] < CONNECTED_TTL_S:
        return _cache[1]
    from hermes_cli.git_credentials import iter_git_basic_auth

    found: GitHubAccount | None = None
    for source, auth in iter_git_basic_auth(GITHUB):
        probe = GitHubAccount("", source, auth)
        try:
            status, body = _request("GET", "/user", probe.authorization(), timeout=timeout)
        except (OSError, ValueError):
            logger.info("git host: github unreachable while probing %s", source)
            return None
        if status == 200 and body.get("login"):
            found = GitHubAccount(str(body["login"]), source, auth)
            break
        logger.info("git host: %s answered %s; trying the next source", source, status)
    _cache = (time.monotonic(), found)
    return found


def create_private_repo(account: GitHubAccount, name: str) -> str:
    """``POST /user/repos`` private, no initial commit; the https clone URL, or :class:`GitHostRefused`."""

    body = {"name": name, "private": True, "auto_init": False, "description": "Eternia Work brain"}
    try:
        status, reply = _request("POST", "/user/repos", account.authorization(), body)
    except (OSError, ValueError) as exc:
        raise GitHostRefused(Reason.HOST_UNREACHABLE, type(exc).__name__) from None
    url = f"{GITHUB}/{account.login}/{name}.git"
    if status == 201 and reply.get("clone_url"):
        logger.info("git host: created private repo %s/%s", account.login, name)
        return str(reply["clone_url"])
    if status == 422 and "already exists" in json.dumps(reply).lower():
        raise GitHostRefused(Reason.REMOTE_EXISTS, url)
    if status in (401, 403):
        raise GitHostRefused(Reason.TOKEN_SCOPE, f"github answered {status} creating {name}")
    raise GitHostRefused(Reason.HOST_UNREACHABLE, f"github answered {status} creating {name}")
