"""The fork's /context manifest carry in ``agent/context_file_sources.py``.

RT-CONTEXT-MANIFEST-SHADOWED (owner ruling 2026-10-18): the fork's
``build_context_files_prompt`` loads every present kind, so the manifest marks
none ``shadowed`` — ``loaded`` is true exactly when the file's body is in the
built prompt.
"""
from __future__ import annotations

from pathlib import Path

from agent.context_file_sources import list_context_file_sources
from agent.prompt_builder import build_context_files_prompt


def test_every_present_kind_the_fork_loads_reports_loaded(tmp_path, tmp_path_factory):
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    (project / ".hermes.md").write_text("hermes rules", encoding="utf-8")
    (project / "AGENTS.md").write_text("agents rules", encoding="utf-8")
    (project / "CLAUDE.md").write_text("claude rules", encoding="utf-8")
    (project / ".cursorrules").write_text("cursor rules", encoding="utf-8")
    home = tmp_path_factory.mktemp("home")

    sources = list_context_file_sources(cwd=str(project), home_override=home)
    prompt = build_context_files_prompt(cwd=str(project), home_override=home)

    statuses = {s["label"]: s["status"] for s in sources}
    assert statuses == {".hermes.md": "loaded", "AGENTS.md": "loaded", "CLAUDE.md": "loaded",
                        ".cursorrules": "loaded"}
    for src in sources:
        body = Path(src["path"]).read_text(encoding="utf-8").strip()
        assert src["loaded"] is (body in prompt), src


def test_manifest_matches_what_the_prompt_actually_loads_with_every_kind_present(tmp_path, tmp_path_factory):
    """The fork's half of upstream's parity test (moved out of
    ``tests/agent/test_context_file_sources.py``, which is at upstream bytes and strict-xfailed by id):
    every context type present at once across a nested directory, an empty file never wins, SOUL.md
    rides along, and every present kind is loaded."""
    project = tmp_path
    (project / ".git").mkdir()
    (project / ".hermes.md").write_text("hermes rules")
    (project / "AGENTS.md").write_text("root agents rules")
    sub = project / "pkg"
    sub.mkdir()
    (sub / "AGENTS.override.md").write_text("")  # empty: falls through to AGENTS.md in the same directory
    (sub / "AGENTS.md").write_text("pkg agents rules")
    (sub / "CLAUDE.md").write_text("claude rules")
    (sub / ".cursorrules").write_text("cursor rules")
    (sub / ".cursor" / "rules").mkdir(parents=True)
    (sub / ".cursor" / "rules" / "a.mdc").write_text("mdc rule a")
    home = tmp_path_factory.mktemp("home")
    (home / "SOUL.md").write_text("identity text")

    sources = list_context_file_sources(cwd=str(sub), home_override=home)
    prompt = build_context_files_prompt(cwd=str(sub), home_override=home)

    statuses = {s["label"]: s["status"] for s in sources}
    assert statuses == {
        ".hermes.md": "loaded", "../AGENTS.md": "loaded", "AGENTS.override.md": "empty", "AGENTS.md": "loaded",
        "CLAUDE.md": "loaded", ".cursorrules": "loaded", ".cursor/rules/a.mdc": "loaded", "SOUL.md": "loaded",
    }
    for src in sources:
        body = Path(src["path"]).read_text().strip() if src["chars"] else ""
        assert src["loaded"] == (bool(body) and body in prompt), src
    assert all(s["est_tokens"] > 0 for s in sources if s["chars"])

    (project / ".hermes.md").unlink()
    statuses = {s["label"]: s["status"] for s in list_context_file_sources(cwd=str(sub), home_override=home)}
    prompt = build_context_files_prompt(cwd=str(sub), home_override=home)
    assert statuses["../AGENTS.md"] == statuses["AGENTS.md"] == "loaded" and "root agents rules" in prompt
    assert statuses["CLAUDE.md"] == "loaded" and "claude rules" in prompt
