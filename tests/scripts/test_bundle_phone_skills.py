"""RT-PHONE-SKILLS-NONE-MARKED: the phone bundle ships its chat-path skills, visible on a phone.

Every tracked skill is upstream's and its ``platforms:`` names desktop OSes only, so a phone
profile filtering on ``[android, ios]`` shipped none (commit ``016de8a203``). The profile now names
its skills (``packaging.skill_names``); the packager ships them and rewrites only the SHIPPED
``SKILL.md`` so upstream's run-time switch (``agent.skill_utils.skill_matches_platform``) shows
them on a phone. Each check carries its control: the same skill, one variable changed.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from agent.skill_utils import parse_frontmatter, skill_matches_platform
from agent_runtime.bundle_profiles.manifest import load_profile
from scripts.bundle_profile_closure import ROOT
from scripts.bundles.bundle_files import mark_named_skill, mark_skill_platforms, skill_ships
from scripts.bundles.verify import resource_problems

PHONE = ("android", "ios")
INLINE = "---\nname: {name}\ndescription: d\nplatforms: [linux, macos, windows]\n---\nbody\nplatforms: not frontmatter\n"
BLOCK = "---\nname: {name}\nplatforms:\n  - linux\n  - windows\ntags: [x]\n---\nbody\n"


def _skill(root, category, name, template=INLINE):
    skill = root / "skills" / category / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(template.format(name=name), encoding="utf-8")
    return skill / "SKILL.md"


def _visible_on(platform, text, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    return skill_matches_platform(parse_frontmatter(text)[0])


def test_a_named_skill_ships_to_a_phone(tmp_path):
    _skill(tmp_path, "cat", "chatty")
    assert skill_ships("skills/cat/chatty/SKILL.md", PHONE, root=tmp_path, _cache={}, skill_names=("chatty",))
    # Control: the same skill, not named, stays out of the phone bundle.
    assert not skill_ships("skills/cat/chatty/SKILL.md", PHONE, root=tmp_path, _cache={}, skill_names=("other",))


@pytest.mark.parametrize("template", [INLINE, BLOCK])
def test_a_marked_copy_is_visible_on_a_phone_and_keeps_its_desktop_platforms(template, monkeypatch):
    text = template.format(name="chatty")
    marked = mark_skill_platforms(text, PHONE)
    assert _visible_on("android", marked, monkeypatch) and _visible_on("ios", marked, monkeypatch)
    assert _visible_on("win32", marked, monkeypatch)
    assert marked.split("\n---\n", 1)[1] == text.split("\n---\n", 1)[1]  # the body is untouched
    # Control: the tracked text is hidden on a phone.
    assert not _visible_on("android", text, monkeypatch)


def test_marking_leaves_an_all_platform_or_already_marked_skill_alone():
    unmarked = "---\nname: any\n---\nbody\n"
    assert mark_skill_platforms(unmarked, PHONE) == unmarked
    phone_ready = "---\nname: p\nplatforms: [android, ios]\n---\nbody\n"
    assert mark_skill_platforms(phone_ready, PHONE) == phone_ready


def test_the_copy_phase_marks_only_named_skills(tmp_path):
    named = _skill(tmp_path, "cat", "chatty")
    other = _skill(tmp_path, "cat", "half", "---\nname: half\nplatforms: [android]\n---\nbody\n")
    assert mark_named_skill(named, PHONE, ("chatty",)) is True
    assert "android, ios" in named.read_text(encoding="utf-8")
    # Control: a skill the profile does not name keeps its own marker (android only), byte for byte.
    before = other.read_bytes()
    assert mark_named_skill(other, PHONE, ("chatty",)) is False and other.read_bytes() == before


def test_verify_reports_a_shipped_skill_the_phone_would_hide(tmp_path):
    app = tmp_path / "app"
    shipped = _skill(app, "cat", "chatty")
    rel = "skills/cat/chatty/SKILL.md"
    problems = resource_problems({rel}, [rel], ("skills",), {}, PHONE, ("chatty",), app)
    assert problems == [f"shipped skill hidden on ['android', 'ios']: app/{rel} names ['linux', 'macos', 'windows']"]
    mark_named_skill(shipped, PHONE, ("chatty",))  # control: the packager's marked copy passes
    assert resource_problems({rel}, [rel], ("skills",), {}, PHONE, ("chatty",), app) == []


def test_the_phone_profile_ships_every_skill_it_names():
    manifest = load_profile("bundled-phone")
    assert manifest.packaging_skill_names, "the phone names its chat-path skills (owner 2026-10-22)"
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "skills"], capture_output=True, text=True,
                             check=True).stdout.split()
    shipped = {parse_frontmatter((ROOT / rel).read_text(encoding="utf-8-sig"))[0].get("name")
               for rel in tracked if rel.endswith("/SKILL.md")
               and skill_ships(rel, manifest.packaging_skill_platforms, _cache={},
                               skill_names=manifest.packaging_skill_names)}
    # A misspelt name would select nothing, silently: every name must reach a tracked skill.
    assert set(manifest.packaging_skill_names) <= shipped
    for rel in tracked:
        if rel.endswith("/SKILL.md") and parse_frontmatter((ROOT / rel).read_text(encoding="utf-8-sig"))[0].get(
                "name") in manifest.packaging_skill_names:
            mark_skill_platforms((ROOT / rel).read_text(encoding="utf-8-sig"), manifest.packaging_skill_platforms)
