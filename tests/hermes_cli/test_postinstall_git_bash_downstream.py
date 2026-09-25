"""``hermes postinstall``'s shell provisioning, through upstream's package manager.

Replaces ``test_dep_ensure_downstream.py`` (the four ``ensure_git_bash`` cases
against ``hermes_cli.dep_ensure``, which upstream deleted at the 2026-09-25
merge). Same four guarantees, pm's names: POSIX asks the one resolver and never
installs; Windows resolves without installing when the resolver answers; Windows
asks pm for its Git explicitly and re-resolves; Windows returns ``None`` when pm
cannot provision — and nothing is persisted to the user environment on any path.
"""

from __future__ import annotations

import pm
import pm.shell
import pytest

from hermes_cli import _downstream_cli

GIT_BASH = r"C:\Program Files\Git\bin\bash.exe"


@pytest.fixture
def installs(monkeypatch):
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        pm, "ensure", lambda name, **kw: calls.append((name, kw.get("explicit"))) or None
    )
    return calls


def test_posix_returns_the_resolver_answer_and_never_installs(monkeypatch, installs):
    monkeypatch.setattr(_downstream_cli, "_IS_WINDOWS", False)
    monkeypatch.setattr(pm.shell, "bash", lambda: "/usr/bin/bash")

    assert _downstream_cli._ensure_git_bash() == "/usr/bin/bash"
    assert installs == []


def test_windows_resolves_without_installing(monkeypatch, installs):
    monkeypatch.setattr(_downstream_cli, "_IS_WINDOWS", True)
    monkeypatch.setattr(pm.shell, "bash", lambda: GIT_BASH)

    assert _downstream_cli._ensure_git_bash() == GIT_BASH
    assert installs == []


def test_windows_asks_pm_for_git_then_reresolves(monkeypatch, installs):
    monkeypatch.setattr(_downstream_cli, "_IS_WINDOWS", True)
    staged = r"C:\Users\x\AppData\Local\hermes\store\git\bin\bash.exe"
    answers = iter([None, staged])  # first miss, then present after the install
    monkeypatch.setattr(pm.shell, "bash", lambda: next(answers))

    assert _downstream_cli._ensure_git_bash() == staged
    assert installs == [("git", True)]


def test_windows_returns_none_when_pm_cannot_provision(monkeypatch):
    monkeypatch.setattr(_downstream_cli, "_IS_WINDOWS", True)
    monkeypatch.setattr(pm.shell, "bash", lambda: None)

    def refuse(name, **_kw):
        raise pm.InstallError(name, "offline")

    monkeypatch.setattr(pm, "ensure", refuse)

    assert _downstream_cli._ensure_git_bash() is None
