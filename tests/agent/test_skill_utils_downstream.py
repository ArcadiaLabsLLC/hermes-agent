"""Fork-owned tests moved out of ``tests/agent/test_skill_utils.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from agent import skill_utils
import pytest
from agent_runtime import skill_resolution
from agent.skill_utils import extract_skill_conditions
from agent_runtime.skill_resolution import (
    required_preload_skill_ids,
    resolve_skill,
    skill_frontmatter_runtime_compatibility,
    skill_package_content_hash,
    skill_runtime_compatibility,
)


# Fork-owned: the canonical skill resolver (resolve_skill / resolve_skills /
# skill_runtime_compatibility / required_preload_skill_ids) and the shared
# skills root are fork surfaces with no upstream counterpart.
def _write_skill(root, name, *, modes=None, load_policy=None):
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    metadata = ""
    if modes or load_policy:
        metadata = (
            "metadata:\n  hermes:\n    surfaces: [mission_chat]\n"
            f"    modes: [{', '.join(modes or ['standard'])}]\n"
            f"    load_policy: {load_policy or 'recommended'}\n"
        )
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test\n{metadata}---\nbody\n",
        encoding="utf-8",
    )
    return skill_dir


def test_canonical_resolver_reports_collision_and_exact_hash(tmp_path):
    local = tmp_path / "local"
    shared = tmp_path / "shared"
    local.mkdir()
    shared.mkdir()
    _write_skill(local, "same")
    shared_skill = _write_skill(shared, "shared-only")

    resolved = resolve_skill("shared-only", roots=[local, shared])
    assert resolved.status == "resolved"
    assert resolved.candidate is not None
    assert skill_package_content_hash(resolved.candidate.skill_dir, resolved.candidate.skill_md)

    _write_skill(shared, "same")
    assert resolve_skill("same", roots=[local, shared]).status == "collision"


def test_runtime_compatibility_rejects_root_only_skill_in_standard_chat(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    _write_skill(root, "lead", modes=["root_node"])
    candidate = resolve_skill("lead", roots=[root]).candidate

    assert skill_runtime_compatibility(
        candidate, surface="mission_chat", root_node_mode=False
    )["reason"] == "mode_not_supported"


@pytest.mark.parametrize(
    "frontmatter",
    [
        # Claude-format skill: metadata dict present, no hermes block at all.
        {"name": "foreign", "metadata": {"short-description": "x"}},
        # Degenerate YAML: `hermes:` key present with a None value.
        {"name": "foreign", "metadata": {"hermes": None}},
        # hermes block is a non-dict scalar (malformed-YAML fallback shape).
        {"name": "foreign", "metadata": {"hermes": "nope"}},
    ],
)
def test_runtime_compatibility_tolerates_non_hermes_metadata(frontmatter):
    """A skill without a usable metadata.hermes block degrades to defaults.

    Regression pin for 2026-07-27: a Claude-format skill moved into the shared
    skills root (metadata present, no hermes key) made
    ``hermes.get("load_policy")`` raise AttributeError on None, which killed
    every mission-chat turn via available_skills_context. One foreign manifest
    must never take down the prompt-observability lane.
    """

    result = skill_frontmatter_runtime_compatibility(
        frontmatter, surface="mission_chat"
    )
    assert result["compatible"] is True
    assert result["load_policy"] == "explicit"


def test_canonical_harness_skill_refuses_non_shared_source_and_duplicates(
    tmp_path, monkeypatch
):

    local = tmp_path / "local"
    shared = tmp_path / "shared"
    local.mkdir()
    shared.mkdir()
    monkeypatch.setattr(skill_resolution, "get_shared_skills_dir", lambda: shared)
    _write_skill(local, "harness-runtime-model")

    assert resolve_skill(
        "harness-runtime-model", roots=[local, shared]
    ).status == "invalid_source"

    _write_skill(shared, "harness-runtime-model")
    assert resolve_skill(
        "harness-runtime-model", roots=[local, shared]
    ).status == "collision"


def test_required_preload_policy_uses_resolver_and_compatibility(tmp_path, monkeypatch):
    import agent.skill_utils as skill_utils

    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(skill_resolution, "get_shared_skills_dir", lambda: shared)
    monkeypatch.setattr(skill_utils, "get_all_skills_dirs", lambda: [shared])
    _write_skill(
        shared,
        "harness-runtime-model",
        modes=["standard"],
        load_policy="required_preload",
    )

    assert required_preload_skill_ids(
        ["harness-runtime-model"], surface="mission_chat"
    ) == ["harness-runtime-model"]


def test_metadata_as_dict_with_hermes():
    """Normal case: metadata is a dict containing hermes keys."""
    frontmatter = {
        "metadata": {
            "hermes": {
                "fallback_for_toolsets": ["toolset_a"],
                "requires_toolsets": ["toolset_b"],
                "fallback_for_tools": ["tool_x"],
                "requires_tools": ["tool_y"],
            }
        }
    }
    result = extract_skill_conditions(frontmatter)
    assert result["fallback_for_toolsets"] == ["toolset_a"]
    assert result["requires_toolsets"] == ["toolset_b"]
    assert result["fallback_for_tools"] == ["tool_x"]
    assert result["requires_tools"] == ["tool_y"]


def test_metadata_as_string_does_not_crash():
    """Bug case: metadata is a non-dict truthy value (e.g. a YAML string)."""
    frontmatter = {"metadata": "some text"}
    result = extract_skill_conditions(frontmatter)
    assert result == {
        "fallback_for_toolsets": [],
        "requires_toolsets": [],
        "fallback_for_tools": [],
        "requires_tools": [],
        "session_platforms": [],
    }


def test_metadata_as_none():
    """metadata key is present but set to null/None."""
    frontmatter = {"metadata": None}
    result = extract_skill_conditions(frontmatter)
    assert result == {
        "fallback_for_toolsets": [],
        "requires_toolsets": [],
        "fallback_for_tools": [],
        "requires_tools": [],
        "session_platforms": [],
    }


def test_metadata_missing_entirely():
    """metadata key is absent from frontmatter."""
    frontmatter = {"name": "my-skill", "description": "Does stuff."}
    result = extract_skill_conditions(frontmatter)
    assert result == {
        "fallback_for_toolsets": [],
        "requires_toolsets": [],
        "fallback_for_tools": [],
        "requires_tools": [],
        "session_platforms": [],
    }


# Fork-owned: resolver/frontmatter mtime caches + batched resolve_skills.
def test_skill_package_content_hash_mtime_cache_invalidates_on_edit(tmp_path):
    """Item 4: the mtime-keyed content-hash cache returns identical hashes on a
    repeat, and a real on-disk edit (mtime/size change) invalidates the entry —
    it is never process-lifetime stale for changed content."""
    import os

    from agent_runtime.skill_resolution import _content_hash_cache_clear, skill_package_content_hash

    _content_hash_cache_clear()
    skill_dir = tmp_path / "s"
    skill_dir.mkdir()
    md = skill_dir / "SKILL.md"
    md.write_text("---\nname: s\n---\nv1\n", encoding="utf-8")

    h1 = skill_package_content_hash(skill_dir, md)
    assert skill_package_content_hash(skill_dir, md) == h1  # cache hit, identical

    # Same-length edit with an explicitly advanced mtime still invalidates
    # (proves the cache keys on mtime, not only size).
    md.write_text("---\nname: s\n---\nvX\n", encoding="utf-8")
    os.utime(md, ns=(1, 5_000_000_000))
    h2 = skill_package_content_hash(skill_dir, md)
    assert h2 != h1

    # The cached value equals a freshly-cleared (uncached) recompute — caching is
    # transparent, only cost differs.
    _content_hash_cache_clear()
    assert skill_package_content_hash(skill_dir, md) == h2


def test_skill_runtime_compatibility_mtime_cache_reflects_edit(tmp_path):
    """Item 3: the frontmatter parse behind skill_runtime_compatibility is
    mtime-cached; editing the manifest (new mtime/size) is reflected, so the
    cache never masks an on-disk change."""
    import os

    from agent_runtime.skill_resolution import (
        SkillResolutionCandidate,
        skill_runtime_compatibility,
    )
    from agent_runtime.parse_cache import clear_parse_cache

    clear_parse_cache()
    skill_dir = tmp_path / "s"
    skill_dir.mkdir()
    md = skill_dir / "SKILL.md"
    md.write_text(
        "---\nname: s\nmetadata:\n  hermes:\n    surfaces: [mission_chat]\n---\nbody\n",
        encoding="utf-8",
    )
    cand = SkillResolutionCandidate(
        root=tmp_path, skill_dir=skill_dir, skill_md=md, source_kind="external"
    )

    assert skill_runtime_compatibility(cand, surface="mission_chat")["compatible"] is True
    # Not yet allowed on mission_worker (proves the frontmatter is actually read).
    assert skill_runtime_compatibility(cand, surface="mission_worker")["compatible"] is False

    md.write_text(
        "---\nname: s\nmetadata:\n  hermes:\n    surfaces: [mission_chat, mission_worker]\n---\nbody\n",
        encoding="utf-8",
    )
    os.utime(md, ns=(1, 5_000_000_000))
    assert skill_runtime_compatibility(cand, surface="mission_worker")["compatible"] is True


def test_resolve_skills_batched_matches_per_name_resolve_skill(tmp_path):
    """Item 2: the batched resolve_skills is behavior-equivalent to per-name
    resolve_skill (same status + same candidate manifests) for present, missing,
    and collision names."""
    from agent_runtime.skill_resolution import resolve_skill, resolve_skills

    local = tmp_path / "local"
    shared = tmp_path / "shared"
    local.mkdir()
    shared.mkdir()
    _write_skill(shared, "alpha")
    _write_skill(local, "collide")
    _write_skill(shared, "collide")
    roots = [local, shared]

    names = ["alpha", "collide", "missing-one"]
    batched = resolve_skills(names, roots=roots)
    for name in names:
        single = resolve_skill(name, roots=roots)
        assert batched[name].status == single.status
        assert [c.skill_md for c in batched[name].candidates] == [
            c.skill_md for c in single.candidates
        ]
    assert batched["alpha"].status == "resolved"
    assert batched["collide"].status == "collision"
    assert batched["missing-one"].status == "missing"


def test_skill_root_registry_reuses_unchanged_roots_and_invalidates_only_changed_root(
    tmp_path,
):
    import os

    from agent_runtime.skill_resolution import (
        _skill_root_registry,
        _skill_root_registry_cache_clear,
    )

    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    _write_skill(root_a, "alpha")
    _write_skill(root_b, "beta")
    _skill_root_registry_cache_clear()

    first_a = _skill_root_registry(root_a)
    first_b = _skill_root_registry(root_b)
    assert _skill_root_registry(root_a) is first_a
    assert _skill_root_registry(root_b) is first_b

    changed = root_a / "alpha" / "SKILL.md"
    changed.write_text("---\nname: renamed-alpha\n---\nchanged\n", encoding="utf-8")
    os.utime(changed, ns=(1, 6_000_000_000))

    assert _skill_root_registry(root_a) is not first_a
    assert _skill_root_registry(root_b) is first_b


def test_cached_skill_registry_preserves_root_precedence_and_profile_classification(
    tmp_path, monkeypatch
):
    from agent import skill_utils

    local = tmp_path / "local"
    shared = tmp_path / "shared"
    local.mkdir()
    shared.mkdir()
    _write_skill(local, "same")
    _write_skill(shared, "same")
    skill_resolution._skill_root_registry_cache_clear()

    monkeypatch.setattr(skill_resolution, "get_skills_dir", lambda: local)
    monkeypatch.setattr(skill_resolution, "get_shared_skills_dir", lambda: shared)
    first = skill_resolution.resolve_skills(["same"], roots=[local, shared])["same"]
    assert first.status == "collision"
    assert [candidate.root for candidate in first.candidates] == [local, shared]
    assert [candidate.source_kind for candidate in first.candidates] == [
        "profile_local",
        "shared_core",
    ]

    # Reuse the same physical registries under another profile classification;
    # source metadata is projected per call, never cached into the root entry.
    other_profile = tmp_path / "other-profile"
    monkeypatch.setattr(skill_resolution, "get_skills_dir", lambda: other_profile)
    second = skill_resolution.resolve_skills(["same"], roots=[shared, local])["same"]
    assert [candidate.root for candidate in second.candidates] == [shared, local]
    assert [candidate.source_kind for candidate in second.candidates] == [
        "shared_core",
        "external",
    ]


def test_one_registry_fingerprint_walk_per_root_per_turn(tmp_path, monkeypatch):
    """A turn's four resolution sites walk each root ONCE between them.

    The four, as the audit found them: the preload policy's
    ``required_preload_skill_ids``; the observability resolver's batch
    ``resolve_skills``; and — the one the plan's §0.3 did not name — the per-NAME
    ``resolve_skill`` behind every ``used_skills`` receipt, which is unbatched
    and therefore walks once per name.

    Sharing one map across all of them is the stage. The assertion is exact
    (``== len(roots)``) rather than "fewer", because "fewer" would pass a change
    that merely batched two of the four.
    """

    local = tmp_path / "local"
    shared = tmp_path / "shared"
    _write_skill(local, "alpha", load_policy="required_preload")
    _write_skill(shared, "beta")
    roots = [local, shared]
    monkeypatch.setattr(skill_utils, "get_all_skills_dirs", lambda: list(roots))
    skill_resolution._skill_root_registry_cache_clear()

    # One turn: one map, handed to every site.
    registries: dict = {}
    skill_resolution.reset_skill_root_walks_for_tests()

    skill_resolution.required_preload_skill_ids(
        ["alpha"], surface="mission_chat", _root_registries=registries
    )
    skill_resolution.resolve_skills(["alpha", "beta"], _root_registries=registries)
    for name in ("alpha", "beta", "alpha", "beta"):
        skill_resolution.resolve_skill(name, _root_registries=registries)

    walks = skill_resolution.skill_root_walks_this_thread()
    assert walks == len(roots), (
        f"one turn must walk each root exactly once; walked {walks} times for "
        f"{len(roots)} roots"
    )

    # A SECOND turn is a second map, and must re-validate the filesystem — the
    # freshness half of CP-4a. "Zero additional walks" is within a turn, never
    # forever.
    skill_resolution.reset_skill_root_walks_for_tests()
    skill_resolution.resolve_skills(["alpha"], _root_registries={})
    assert skill_resolution.skill_root_walks_this_thread() == len(roots), (
        "a later turn must re-stat its roots; a memo that outlived the turn "
        "would be a staleness window, which CP-4 refuses"
    )


def test_unshared_resolution_still_walks_per_site(tmp_path, monkeypatch):
    """The control that gives the test above its meaning.

    Without a shared map every site walks for itself. This is the pre-Stage-8
    behaviour, and it is pinned so the counter cannot silently start counting
    something cheaper.
    """

    local = tmp_path / "local"
    _write_skill(local, "alpha")
    monkeypatch.setattr(skill_utils, "get_all_skills_dirs", lambda: [local])
    skill_resolution._skill_root_registry_cache_clear()

    skill_resolution.reset_skill_root_walks_for_tests()
    skill_resolution.resolve_skills(["alpha"])
    skill_resolution.resolve_skill("alpha")
    skill_resolution.resolve_skill("alpha")
    assert skill_resolution.skill_root_walks_this_thread() == 3, (
        "each unshared site pays its own walk — if this drops, the counter is "
        "measuring calls rather than filesystem work"
    )


def test_next_turn_manifest_add_edit_delete_and_org_flip_invalidate(
    tmp_path, monkeypatch
):
    """Sharing must not outlive the turn: the next turn sees real changes.

    Add, edit and delete, each read on a FRESH map the way a new turn would,
    with an unrelated root left alone throughout. Alias/collision behaviour is
    asserted across the change so sharing cannot quietly flatten two candidates
    into one.
    """

    local = tmp_path / "local"
    shared = tmp_path / "shared"
    _write_skill(local, "alpha")
    _write_skill(shared, "beta")
    roots = [local, shared]
    monkeypatch.setattr(skill_utils, "get_all_skills_dirs", lambda: list(roots))
    skill_resolution._skill_root_registry_cache_clear()

    first = skill_resolution.resolve_skills(["alpha", "beta", "gamma"], _root_registries={})
    assert first["alpha"].status == "resolved"
    assert first["gamma"].status == "missing"

    # ADD, on the next turn's own map.
    _write_skill(local, "gamma")
    after_add = skill_resolution.resolve_skills(["gamma"], _root_registries={})
    assert after_add["gamma"].status == "resolved", "an added skill must appear"

    # COLLISION: the same name in a second root is still two candidates.
    _write_skill(shared, "gamma")
    after_collision = skill_resolution.resolve_skills(["gamma"], _root_registries={})
    assert after_collision["gamma"].status == "collision", (
        "a shared walk must not flatten a collision into a silent winner"
    )

    # DELETE one side; the collision resolves back to a single candidate.
    (shared / "gamma" / "SKILL.md").unlink()
    (shared / "gamma").rmdir()
    after_delete = skill_resolution.resolve_skills(["gamma"], _root_registries={})
    assert after_delete["gamma"].status == "resolved"

    # The unrelated root was never disturbed by any of it.
    assert skill_resolution.resolve_skills(["beta"], _root_registries={})["beta"].status == (
        "resolved"
    )


def test_a_shared_map_is_keyed_by_root_so_lanes_with_different_roots_are_safe(
    tmp_path, monkeypatch
):
    """CP-5a: the two lanes may enumerate DIFFERENT root lists.

    ``mission_chat_prompt_observability`` runs inside ``persona_profile_scope``
    and the context builder does not, so for a persona whose profile is not the
    ambient one the lists can differ. The map is keyed by RESOLVED ROOT PATH,
    which is what makes the hand-off safe without the lanes having to agree: a
    root both lanes see is walked once, a root only one lane sees is walked by
    that lane, and no lane is served a root it did not ask for.
    """

    a = tmp_path / "a"
    b = tmp_path / "b"
    _write_skill(a, "alpha")
    _write_skill(b, "beta")
    skill_resolution._skill_root_registry_cache_clear()

    registries: dict = {}
    skill_resolution.reset_skill_root_walks_for_tests()

    # Lane one sees only `a`.
    first = skill_resolution.resolve_skills(["alpha"], roots=[a], _root_registries=registries)
    assert first["alpha"].status == "resolved"
    assert skill_resolution.skill_root_walks_this_thread() == 1

    # Lane two sees `a` and `b`: it reuses `a` and walks only the new root.
    second = skill_resolution.resolve_skills(
        ["alpha", "beta"], roots=[a, b], _root_registries=registries
    )
    assert second["alpha"].status == "resolved"
    assert second["beta"].status == "resolved"
    assert skill_resolution.skill_root_walks_this_thread() == 2, (
        "the second lane must walk only the root the first had not already taken"
    )

    # And a lane restricted to `b` is not handed `a`'s skills.
    third = skill_resolution.resolve_skills(["alpha"], roots=[b], _root_registries=registries)
    assert third["alpha"].status == "missing", (
        "a shared map must never widen a lane's root list"
    )


def test_shared_resolver_excludes_package_markdown_but_keeps_legacy_skills(tmp_path):
    """Tool reads and runtime policy must agree on package-owned support files."""
    _write_skill(tmp_path, "research")
    _write_skill(tmp_path, "character")
    internal = tmp_path / "character" / "prompts" / "research.md"
    internal.parent.mkdir()
    internal.write_text("Internal prompt, not a standalone skill", encoding="utf-8")
    legacy = tmp_path / "legacy" / "standalone.md"
    legacy.parent.mkdir()
    legacy.write_text("Legacy standalone skill", encoding="utf-8")
    names = ["research", "character/prompts/research", "legacy/standalone"]
    batch = skill_resolution.resolve_skills(names, roots=[tmp_path])
    for name in names:
        single = skill_resolution.resolve_skill(name, roots=[tmp_path])
        assert single.status == batch[name].status
        assert single.candidates == batch[name].candidates
    assert batch["research"].status == "resolved"
    assert batch["research"].candidates[0].skill_md == tmp_path / "research" / "SKILL.md"
    assert batch["character/prompts/research"].status == "missing"
    assert batch["legacy/standalone"].status == "resolved"
