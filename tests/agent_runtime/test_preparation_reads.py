"""Request-only reuse; fresh authorities and filesystem edits remain observable."""
import json
import os
import threading
from contextvars import ContextVar
from pathlib import Path

import pytest

from agent_runtime.preparation_reads import InstanceReadEpoch, SkillPreparationEpoch
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments.store import PersonaInstanceStore
from agent_runtime.states import WorkerSessionState
from agent_runtime.serde import to_jsonable
from agent_runtime.skill_resolution import SkillResolutionCandidate, skill_runtime_compatibility


def seed(root, name, **fields):
    root.mkdir(parents=True, exist_ok=True)
    row = PersonaInstance(id=name, persona_id=name, role="developer", display_name=name,
                          profile_id=None, runtime_root=str(root), state=WorkerSessionState.IDLE, **fields)
    (root / f"{name}.json").write_text(json.dumps(to_jsonable(row)), encoding="utf-8")
    return row


@pytest.fixture
def instances(tmp_path, monkeypatch):
    from agent_runtime import paths
    root = tmp_path / "instances"
    for n in range(256): seed(root, f"i{n}")
    monkeypatch.setattr(paths, "persona_instances_dir", lambda: root)
    monkeypatch.setattr(paths, "persona_instance_path", lambda name: root / f"{name}.json")
    return root


def test_256_row_epoch_reuses_decodes_but_authority_reads_fresh(instances, monkeypatch):
    original = Path.read_text
    reads = []
    def read(path, *args, **kwargs):
        if path.parent == instances: reads.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    epoch = InstanceReadEpoch(); store = PersonaInstanceStore(preparation_epoch=epoch)
    first = epoch.scan(store); second = epoch.scan(store)
    assert len(first.instances) == len(second.instances) == 256
    assert len(reads) == 256
    first.instances[0].display_name = "local mutation"
    first.instances[0].steered_by.append("poison")
    reread = epoch.scan(store)
    assert reread.instances[0].display_name != "local mutation"
    assert "poison" not in reread.instances[0].steered_by
    # Binding's authoritative scan never opts into preparation reuse, even
    # when no file changed and the preparation epoch would be a cache hit.
    before_authority = len(reads)
    assert not store._session_owned_by_other_instance("unowned", "i0")
    assert len(reads) == before_authority + 256
    seed(instances, "owner", default_chat_session_id="claimed")
    assert store._session_owned_by_other_instance("claimed", "i0")
    (instances / "i1.json").write_text("broken", encoding="utf-8")
    from agent_runtime.errors import PersonaInstancesUnreadable
    with pytest.raises(PersonaInstancesUnreadable): store._session_owned_by_other_instance("claimed", "i0")
    print("INSTANCE: two projection scans 512->256 JSON reads; admission scans remain fresh")


@pytest.mark.parametrize("mutation", ["create", "delete", "rename", "corrupt", "edit", "replace"])
def test_instance_middle_mutation_and_new_request_are_fresh(instances, mutation):
    store = PersonaInstanceStore(); epoch = InstanceReadEpoch(); before = epoch.scan(store)
    fingerprint_before = epoch._entry[0]
    file = instances / "i0.json"
    if mutation == "create": seed(instances, "new")
    elif mutation == "delete": file.unlink()
    elif mutation == "rename": file.rename(instances / "renamed.json")
    elif mutation == "corrupt": file.write_text("broken", encoding="utf-8")
    elif mutation == "edit":
        row = json.loads(file.read_text(encoding="utf-8")); row["display_name"] = "edited"; file.write_text(json.dumps(row), encoding="utf-8")
    else:
        replacement = instances / "temp"; replacement.write_text(file.read_text(encoding="utf-8").replace('"i0",', '"xx",', 1), encoding="utf-8")
        old_stat = file.stat(); os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns)); replacement.replace(file)
    actual = epoch.scan(store)
    assert actual == store.scan_all() == InstanceReadEpoch().scan(store)
    if mutation != "rename": assert actual != before
    else: assert epoch._entry[0] != fingerprint_before


def test_store_write_invalidates_epoch_even_without_stamp_change(instances, monkeypatch):
    epoch = InstanceReadEpoch(); store = PersonaInstanceStore(preparation_epoch=epoch)
    epoch.scan(store); assert epoch._entry is not None
    unchanged_receipt = epoch._fingerprint(instances)
    monkeypatch.setattr(epoch, "_fingerprint", lambda root: unchanged_receipt)
    row = store.get("i0"); row.display_name = "write"
    store._write(row)
    assert epoch._entry is None
    assert any(row.display_name == "write" for row in epoch.scan(store).instances)
    epoch.close(); assert epoch._entry is None


def test_concurrent_instance_requests_keep_root_and_values_separate(tmp_path, monkeypatch):
    from agent_runtime import paths
    root_scope = ContextVar("test_instance_root")
    monkeypatch.setattr(paths, "persona_instances_dir", root_scope.get)
    roots = [tmp_path / "a", tmp_path / "b"]
    for root in roots: seed(root, root.name)
    barrier = threading.Barrier(2); results = []; errors = []
    def read(root):
        root_scope.set(root)
        try:
            epoch = InstanceReadEpoch(); store = PersonaInstanceStore()
            barrier.wait(timeout=2)
            for _ in range(2): assert epoch.scan(store).instances[0].id == root.name
            results.append(root.name)
        except Exception as exc: errors.append(exc)
    threads = [threading.Thread(target=read, args=(root,), daemon=True) for root in roots]
    for thread in threads: thread.start()
    for thread in threads: thread.join(2)
    assert not errors and sorted(results) == ["a", "b"] and not any(t.is_alive() for t in threads)


def skill(root, name="skill", surface="mission_chat"):
    directory = root / name; directory.mkdir(parents=True, exist_ok=True); md = directory / "SKILL.md"
    md.write_text(f"---\nmetadata:\n  hermes:\n    surfaces: [{surface}]\n---\nBody", encoding="utf-8")
    return SkillResolutionCandidate(root, directory, md, "local")


def test_186_skill_epoch_checks_each_stamp_once_per_request(tmp_path, monkeypatch):
    candidates = [skill(tmp_path, f"s{n}") for n in range(186)]
    files = {candidate.skill_md for candidate in candidates}; original = Path.stat; stats = []
    def stat(path, *args, **kwargs):
        if path in files: stats.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", stat)
    epoch = SkillPreparationEpoch()
    for mode in [False, True]:
        for candidate in candidates:
            assert skill_runtime_compatibility(candidate, surface="mission_chat", root_node_mode=mode, preparation_epoch=epoch)["compatible"]
    assert len(stats) == 186
    epoch.close()
    next_epoch = SkillPreparationEpoch()
    for candidate in candidates: skill_runtime_compatibility(candidate, surface="mission_chat", preparation_epoch=next_epoch)
    assert len(stats) == 372
    print("SKILLS: two prep evaluations 372->186 manifest stats; next request validates 186 again")


def test_skill_middle_edit_keeps_snapshot_but_fresh_authorization_refuses(tmp_path):
    candidate = skill(tmp_path); epoch = SkillPreparationEpoch()
    assert skill_runtime_compatibility(candidate, surface="mission_chat", preparation_epoch=epoch)["compatible"]
    skill(tmp_path, surface="mission_worker")
    assert not skill_runtime_compatibility(candidate, surface="mission_chat")["compatible"]
    assert not skill_runtime_compatibility(candidate, surface="mission_chat", preparation_epoch=SkillPreparationEpoch())["compatible"]
    epoch.invalidate()
    assert not skill_runtime_compatibility(candidate, surface="mission_chat", preparation_epoch=epoch)["compatible"]
    epoch.close()
    skill(tmp_path)
    assert skill_runtime_compatibility(candidate, surface="mission_chat", preparation_epoch=epoch)["compatible"]


def test_skill_replacement_same_mtime_and_size_invalidates_parse_owner(tmp_path):
    candidate = skill(tmp_path, surface="mission_chat"); epoch = SkillPreparationEpoch()
    assert epoch.frontmatter(candidate.skill_md)["metadata"]["hermes"]["surfaces"] == ["mission_chat"]
    old_stat = candidate.skill_md.stat(); replacement = tmp_path / "replacement"
    replacement.write_text(candidate.skill_md.read_text(encoding="utf-8").replace("mission_chat", "mission_work"), encoding="utf-8")
    assert replacement.stat().st_size == old_stat.st_size
    os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns)); replacement.replace(candidate.skill_md)
    assert SkillPreparationEpoch().frontmatter(candidate.skill_md)["metadata"]["hermes"]["surfaces"] == ["mission_work"]


def test_skill_create_delete_corruption_and_root_isolation(tmp_path):
    a = skill(tmp_path / "a"); b = skill(tmp_path / "b", surface="mission_worker")
    epoch = SkillPreparationEpoch()
    assert epoch.frontmatter(a.skill_md) != epoch.frontmatter(b.skill_md)
    a.skill_md.unlink()
    assert SkillPreparationEpoch().frontmatter(a.skill_md) == {}
    a.skill_md.write_text("broken", encoding="utf-8")
    assert SkillPreparationEpoch().frontmatter(a.skill_md) == {}
    skill(tmp_path / "a")
    assert SkillPreparationEpoch().frontmatter(a.skill_md)["metadata"]["hermes"]["surfaces"] == ["mission_chat"]


def test_roster_ensure_and_actual_target_share_one_projection_scan(instances, monkeypatch):
    from tests.agent_runtime.persona_samples import sample_personas
    from agent_runtime import persona_assignments
    from hermes_cli.harness_parts.persona.chat_target import _mission_chat_target_decision
    epoch = InstanceReadEpoch(); store = PersonaInstanceStore(preparation_epoch=epoch)
    personas = sample_personas()[:2]; calls = []
    def ensure(persona):
        calls.append(persona.id)
        return PersonaInstance(id=persona.id, persona_id=persona.id, role="developer", display_name=persona.id,
                               profile_id=None, runtime_root=str(instances), state=WorkerSessionState.IDLE, mode="chat")
    monkeypatch.setattr(store, "ensure_for_persona", ensure)
    monkeypatch.setattr(persona_assignments, "sender_scope_workspace_id", lambda *args, **kwargs: None)
    original = Path.read_text; reads = []
    def read(path, *args, **kwargs):
        if path.parent == instances: reads.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    store.ensure_for_personas(personas, read_epoch=epoch)
    result = _mission_chat_target_decision(instance_store=store, normalized_persona="i0", raw_persona_id="i0",
                                         persona_instance_id=None, session_id=None, relay_chain=[], instance_read_epoch=epoch)
    assert result.allowed
    assert len(calls) == len(personas)
    assert len(reads) == 256


def test_concurrent_skill_preparation_requests_keep_profiles_separate(tmp_path):
    candidates = [skill(tmp_path / "a"), skill(tmp_path / "b", surface="mission_worker")]
    barrier = threading.Barrier(2); errors = []; results = []
    def prepare(index):
        try:
            epoch = SkillPreparationEpoch(); barrier.wait(timeout=2)
            for _ in range(2):
                value = skill_runtime_compatibility(candidates[index], surface="mission_chat", preparation_epoch=epoch)["compatible"]
                assert value is (index == 0)
            epoch.close(); results.append(index)
        except Exception as exc: errors.append(exc)
    threads = [threading.Thread(target=prepare, args=(index,), daemon=True) for index in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(2)
    assert not errors and sorted(results) == [0, 1] and not any(t.is_alive() for t in threads)


def test_manifest_read_denial_does_not_leak_into_fresh_request(tmp_path, monkeypatch):
    candidate = skill(tmp_path, surface="mission_worker")
    from agent_runtime.parse_cache import clear_parse_cache
    clear_parse_cache()
    original = Path.read_text
    def denied(path, *args, **kwargs):
        if path == candidate.skill_md: raise PermissionError("isolated denial")
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", denied)
        assert SkillPreparationEpoch().frontmatter(candidate.skill_md) == {}
    assert not skill_runtime_compatibility(candidate, surface="mission_chat")["compatible"]


def test_actual_preload_and_catalog_share_request_manifest_epoch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agent_runtime import skill_resolution
    from agent_runtime.skill_root_freshness import TurnRootRegistries
    from agent_runtime.prompt_observability import skills_context, skills_resolver
    candidates = [skill(tmp_path, f"s{n}") for n in range(186)]
    resolutions = {f"s{n}": SimpleNamespace(candidate=candidate, status="resolved")
                   for n, candidate in enumerate(candidates)}
    monkeypatch.setattr(skill_resolution, "resolve_skills", lambda *args, **kwargs: resolutions)
    turn_map = TurnRootRegistries()
    resolver = skills_resolver._SkillObservabilityResolver(root_registries=turn_map)
    assert resolver.preparation_epoch is turn_map.preparation_epoch
    monkeypatch.setattr(resolver, "resolve", lambda *args, **kwargs: resolutions)
    monkeypatch.setattr(resolver, "shared_catalog", lambda: {})
    monkeypatch.setattr(resolver, "realm_publish_states", lambda: [])
    monkeypatch.setattr(skills_context, "_installed_skill_catalog", lambda: [{"name": name} for name in resolutions])
    files = {candidate.skill_md for candidate in candidates}; original = Path.stat; stats = []
    def stat(path, *args, **kwargs):
        if path in files: stats.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", stat)
    assert skill_resolution.required_preload_skill_ids(list(resolutions), surface="mission_chat", _root_registries=turn_map) == []
    rows = skills_context.available_skills_context(skill_resolver=resolver, limit=186)
    assert len(rows) == 186 and all(row["loadable"] for row in rows)
    assert len(stats) == 186


def test_retirement_explicitly_invalidates_preparation_rows(instances, monkeypatch, tmp_path):
    from agent_runtime.persona_assignments.retire import _archive_instance_row
    epoch = InstanceReadEpoch(); store = PersonaInstanceStore(preparation_epoch=epoch)
    epoch.scan(store)
    monkeypatch.setattr(store, "_release_parent_references", lambda instance_id: None)
    archived = _archive_instance_row(store, store.get("i0"), tmp_path / "archive")
    assert archived.exists() and not (instances / "i0.json").exists()
    assert epoch._entry is None
    assert len(epoch.scan(store).instances) == 255
