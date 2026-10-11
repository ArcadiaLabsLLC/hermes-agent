"""D1.05 CF-1 — one parser of a SKILL.md manifest per process.

``_skill_root_registry`` used to parse every manifest with
``skill_utils.parse_frontmatter(manifest.read_text())`` directly, while the
compatibility pass read the same files through ``_cached_skill_frontmatter``
(``parse_cache.cached_by_mtime``). Two parsers of one file: every manifest was
parsed twice in a cold build (2,004 parses, ~4.8 s on the operator's store,
plan ``design-sweep-d1-2026-10-10.md`` § D1.05).

Killing mutation: restore the direct ``parse_frontmatter`` call in
``_skill_root_registry`` -> 80 parses for 40 manifests, not 40.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import skill_utils
from agent_runtime import parse_cache
from agent_runtime import skill_resolution as sr

_MANIFESTS = 40


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    for index in range(_MANIFESTS):
        manifest = root / f"skill-{index:02d}" / "SKILL.md"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            f"---\nname: declared-{index:02d}\nmetadata:\n  hermes:\n"
            f"    load_policy: explicit\n---\nbody {index}\n",
            encoding="utf-8",
        )
    sr._skill_root_registry_cache_clear()
    parse_cache.clear_parse_cache()
    yield root
    sr._skill_root_registry_cache_clear()
    parse_cache.clear_parse_cache()


def test_a_registry_build_and_a_compatibility_pass_parse_each_manifest_once(root, monkeypatch):
    calls: list[str] = []
    real = skill_utils.parse_frontmatter

    def counting(content: str):
        calls.append(content)
        return real(content)

    monkeypatch.setattr(skill_utils, "parse_frontmatter", counting)

    registry = sr._skill_root_registry(root)
    assert len(registry.manifests) == _MANIFESTS
    # The declared name still reaches the alias table (the parse was not skipped).
    assert "declared-07" in registry.manifests_by_alias

    for skill_dir, manifest in registry.manifests:
        candidate = sr.SkillResolutionCandidate(root, skill_dir, manifest, "test")
        verdict = sr.skill_runtime_compatibility(candidate, surface="chat")
        assert verdict["compatible"] is True
        assert verdict["load_policy"] == "explicit"

    assert len(calls) == _MANIFESTS, (
        f"{len(calls)} parses for {_MANIFESTS} manifests: the registry build and the "
        "compatibility pass must share one parser (_cached_skill_frontmatter)"
    )


def test_a_malformed_manifest_still_registers_under_its_directory_name(root):
    bad = root / "broken" / "SKILL.md"
    bad.parent.mkdir()
    bad.write_bytes(b"\xff\xfe not utf-8 \x00")
    sr._skill_root_registry_cache_clear()

    registry = sr._skill_root_registry(root)

    assert "broken" in registry.manifests_by_alias
