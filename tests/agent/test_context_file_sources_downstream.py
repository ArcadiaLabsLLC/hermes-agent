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
