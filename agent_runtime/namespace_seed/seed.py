"""``hermes namespace seed`` — the seed plan and copy (row RT-NAMESPACE-CLI), moved out of ``namespace_admin``.

Plan: ``EterniaLauncher/docs/embedded_hermes/planned/ONE_HERMES_INSTALL_PROFILE_NAMESPACE_2026-10-19.md``
§2.4, §2.8, §3, §4 H3; owner rulings Q3/Q4 (the seed carries config, SOUL, skills, skins, world and
persona definitions, never credentials, sessions, pairing or realm_sync) and Q11 (a namespace is
seeded AT MOST ONCE, when it is created — never per launch; ``reset`` empties it, after which a
seed is again an explicit operator act).

The allowlists and :data:`NEVER_SEED` moved here from the launcher's
``EterniaLauncher/tool/stagec_qa_mcp_server/lib/hermes_parity_seed.dart``; this module is now the
one authority. Persona DEFINITIONS (``agent-runtime/agents/``) are copied; persona INSTANCES
(``agent-runtime/persona_instances/``) are never copied AS-IS — :mod:`.instances` carries each one
rebased (row RT-NAMESPACE-SEED-HIRED-INSTANCES, owner 2026-10-19), because the office the seed copies
places hired instances boot never re-mints. Chats move by ``hermes namespace import-sessions``
(row RT-SESSIONS-IMPORT-OWN-EXPORT), never by a seed.

Developer Edition only (owner 2026-10-19): ``hermes_cli.namespace_cmd`` refuses ``seed`` on the
bundled edition before importing this package, and the bundled profiles switch it off.

A seed is planned before it copies (:func:`plan_seed`, read-only): every source entry is either
copied, skipped with a :class:`SkipReason`, or listed as code the namespace borrows from the base
root (:data:`BORROWED`). ``seed --dry-run`` prints that plan and writes nothing; a real seed returns
the same lists and records them in the manifest beside ``seeded_from``.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from hermes_cli._namespace_bootstrap import (
    ACCOUNT_ID,
    BASE_ID,
    MANIFEST_NAME,
    STORE_DIRNAME,
    Layout,
    NamespaceRefused,
    Reason,
    ensure_manifest,
    layout,
    validate_id,
)

from ..namespace_admin import (
    _exclusive,
    _namespace_manifest,
    _now,
    _write_manifest,
    epoch_admitted,
    existing_namespace,
    restamped,
)
from ..redaction import has_secret_value
from .instances import HANDLED as INSTANCES_HANDLED
from .instances import InstancePlan, plan_instances, write_instances

__layer__ = "lanes"

#: Profile-home entries a seed copies (the root's own and each ``profiles/<name>/``'s): config
#: (``profile.yaml`` is the profile's own metadata), SOUL, skills, skins, and the persona prompt files
#: (``personas/``, realm sync's ``PERSONA_PROMPT_DIR``) persona definitions point at.
HOME_SEED = ("config.yaml", "profile.yaml", "SOUL.md", "skills", "skins", "personas", "pets")
#: Runtime-store entries: the world definitions (realm sync's world families, prefabs included) and
#: the persona definitions.
STORE_SEED = ("realms", "workspaces", "levels", "maps", "prefabs", "office", "active_realm.json",
              "active_workspace.json", "agents", "flow_graphs", "workspace_slots")
#: Root entries: the machine-root registry.
ROOT_SEED = ("machine_roots.json",)
#: ``<root>/shared/`` entries: the install-wide skills and character libraries every profile reads
#: (``profile_home.get_shared_skills_dir`` / ``get_shared_characters_dir``).
SHARED_DIRNAME = "shared"
SHARED_SEED = ("skills", "characters")
#: The profile memory a seed copies ONLY on ``--with-memories`` into an ``acct-`` namespace (owner ruling
#: 2026-10-19, row RT-NAMESPACE-SEED-OWNER-SET: "carry memories (opt-in, my reseed only)").
MEMORIES = "memories"
#: Install-level code a namespace BORROWS from the base root (``HERMES_DEPENDENCY_ROOT``); never copied.
BORROWED = ("installs", "venvs", "bin", "builds", "tools", "runtimes")
#: Names a seed never copies at ANY depth, whatever an allowlist says.
NEVER_SEED = re.compile(
    r"^(auth\.json|auth\.lock|credential_rotation\.json|\.env.*|.*\.db(-shm|-wal)?|state\.db.*|"
    r"sessions|pairing|memories|backups|state-snapshots|chat_live_logs|logs|"
    r"realm_sync|\.git|secure-store|gateway|install_id|persona_instances)$",
    re.IGNORECASE,
)
#: A name carrying a secret word. At an allowlist level (and for any directory) it is never copied.
#: INSIDE an allowlisted tree a FILE so named is decided by its value (``redaction.has_secret_value``):
#: a word is not a secret, and the word alone dropped 114 skill files from the owner's root
#: (``…-token-budget….md``, ``git-credential-token.py``) and left those skills broken.
SECRET_WORD_NAME = re.compile(r"^.*(token|secret|credential|password).*$", re.IGNORECASE)
#: The largest word-named file a seed reads to decide it; a larger one is not copied.
SECRET_WORD_READ_LIMIT = 256 * 1024


def allowlist_violations(names: tuple[str, ...]) -> list[str]:
    """Entries no seed may copy: a never-seed name, or anything that is not one plain path segment."""
    return [
        name for name in names
        if name != name.strip() or name in ("", ".", "..") or "/" in name or "\\" in name or NEVER_SEED.match(name)
        or SECRET_WORD_NAME.match(name)
    ]




class SkipReason(StrEnum):
    """Why a seed did not copy a source entry; every skip carries exactly one."""

    NEVER_SEED = "never_seed"  #: a NEVER_SEED name (secret, runtime state, DB, log, pairing, instance)
    SECRET_VALUE = "secret_value"  #: a secret-word-named file that holds a secret value (or cannot be read)
    SYMLINK = "symlink"  #: a link, at any depth — a seed copies bytes, never a pointer back into the source
    NOT_ALLOWLISTED = "not_allowlisted"  #: present in the source, on no allowlist (caches, backups, …)
    MEMORIES_OPT_IN = "opt-in: --with-memories, acct- namespaces only"  #: owner ruling 2026-10-19
    RULED_CODE = "owner ruled 2026-10-19: runs or schedules code"  #: cron, hooks, plugins, scripts
    RULED_WORK_STATE = "owner ruled 2026-10-19: work state"  #: boards, kanban


#: Allowlist-level names the owner ruled out of every seed (2026-10-19), with the ruling as the reason.
RULED_OUT: dict[str, SkipReason] = {
    **dict.fromkeys(("cron", "hooks", "plugins", "scripts"), SkipReason.RULED_CODE),
    **dict.fromkeys(("boards", "kanban", "kanban.db", "kanban.db-shm", "kanban.db-wal"), SkipReason.RULED_WORK_STATE),
}


@dataclass(frozen=True, slots=True)
class SeedPlan:
    """What a seed copies (source, destination, label), what it skips and why, and what it borrows."""

    copies: tuple[tuple[Path, Path, str], ...]
    skipped: tuple[dict[str, str], ...]
    borrowed: tuple[str, ...]
    instances: InstancePlan

    def payload(self) -> dict[str, Any]:
        return {"copied": [rel for _src, _dst, rel in self.copies], "skipped": list(self.skipped),
                "borrowed": list(self.borrowed), "instances": self.instances.payload()}


def _seed_refusal(path: Path, *, nested: bool = False) -> SkipReason | None:
    """The ONE predicate a plan and a copy share: why ``path`` is never copied, or ``None``.

    ``nested``: ``path`` lies inside an allowlisted tree, where a secret-word FILE is read and judged
    by its value; anywhere else a secret-word name is refused unread.
    """
    if path.is_symlink():
        return SkipReason.SYMLINK
    if NEVER_SEED.match(path.name):
        return SkipReason.NEVER_SEED
    if not SECRET_WORD_NAME.match(path.name):
        return None
    if not nested or not path.is_file():
        return SkipReason.NEVER_SEED
    try:
        if path.stat().st_size > SECRET_WORD_READ_LIMIT:
            return SkipReason.SECRET_VALUE
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return SkipReason.SECRET_VALUE
    return SkipReason.SECRET_VALUE if has_secret_value(text) else None


def _skip(skipped: list[dict[str, str]], rel: str, reason: SkipReason) -> None:
    skipped.append({"path": rel, "reason": reason.value})


def _entry_reason(entry: Path, allowlist: tuple[str, ...]) -> SkipReason | None:
    """Why an allowlist-level entry is not copied: a link, the owner's ruling, never-seed, or no allowlist."""
    if entry.is_symlink():
        return SkipReason.SYMLINK
    if entry.name in RULED_OUT:
        return RULED_OUT[entry.name]
    if entry.name == MEMORIES:
        return None if MEMORIES in allowlist else SkipReason.MEMORIES_OPT_IN
    return _seed_refusal(entry) or (None if entry.name in allowlist else SkipReason.NOT_ALLOWLISTED)


def _plan_dir(src: Path, dst: Path, rel: str, allowlist: tuple[str, ...], plan: list, skipped: list,
              handled: frozenset[str] = frozenset()) -> None:
    """Plan one directory level: allowlisted entries copy, every other entry is a reasoned skip.

    ``handled`` names real directories another step plans (the root's ``profiles/``, ``shared/``, the
    store and the borrowed code). A link is never followed, here or by a caller.
    """
    if src.is_symlink() or not src.is_dir():
        return
    for entry in sorted(src.iterdir(), key=lambda p: p.name):
        if entry.name in handled and not entry.is_symlink():
            continue
        label = f"{rel}{entry.name}"
        reason = _entry_reason(entry, allowlist)
        if reason is not None:
            _skip(skipped, label, reason)
            continue
        plan.append((entry, dst / entry.name, label))
        for folder, dirs, files in os.walk(entry) if entry.is_dir() else ():
            for name in sorted(dirs + files):
                inner = Path(folder) / name
                if (why := _seed_refusal(inner, nested=True)) is not None:
                    _skip(skipped, f"{label}/{inner.relative_to(entry).as_posix()}", why)
            dirs[:] = [d for d in dirs if _seed_refusal(Path(folder) / d, nested=True) is None]


def plan_seed(src_root: Path, item: Layout, *, with_memories: bool = False) -> SeedPlan:
    """Read-only: the exact seed of ``item`` from ``src_root``. Writes nothing (``--dry-run`` prints it)."""
    home = HOME_SEED + ((MEMORIES,) if with_memories else ())
    copies: list[tuple[Path, Path, str]] = []
    skipped: list[dict[str, str]] = []
    borrowed = tuple(name for name in BORROWED if (src_root / name).is_dir() and not (src_root / name).is_symlink())
    handled = frozenset({"profiles", SHARED_DIRNAME, STORE_DIRNAME, *borrowed})
    _plan_dir(src_root, item.root, "", ROOT_SEED + home, copies, skipped, handled)
    _plan_dir(src_root / SHARED_DIRNAME, item.root / SHARED_DIRNAME, f"{SHARED_DIRNAME}/", SHARED_SEED, copies, skipped)
    _plan_dir(src_root / STORE_DIRNAME, item.store_root, f"{STORE_DIRNAME}/", STORE_SEED, copies, skipped,
              INSTANCES_HANDLED)
    profiles = src_root / "profiles"
    listed = profiles.is_dir() and not profiles.is_symlink()
    for profile in sorted(profiles.iterdir(), key=lambda p: p.name) if listed else []:
        rel = f"profiles/{profile.name}"
        if not profile.is_dir() or profile.name.startswith(".") or allowlist_violations((profile.name,)):
            _skip(skipped, rel, _seed_refusal(profile) or SkipReason.NOT_ALLOWLISTED)
            continue
        _plan_dir(profile, item.root / "profiles" / profile.name, f"{rel}/", home, copies, skipped)
    return SeedPlan(tuple(copies), tuple(skipped), borrowed, plan_instances(src_root, item))


def _copy(src: Path, dst: Path) -> None:
    """Copy one planned entry; a never-seed name or a link at any depth stays behind (the plan lists it)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, symlinks=False, dirs_exist_ok=True,
                        ignore=lambda folder, names: {n for n in names if _seed_refusal(Path(folder) / n, nested=True) is not None})
    else:
        shutil.copy2(src, dst)


def _assert_fresh(item: Layout, manifest: Mapping[str, Any]) -> None:
    if manifest.get("seeded_at"):
        raise NamespaceRefused(Reason.ALREADY_SEEDED,
                               f"{item.id!r} was seeded from {manifest.get('seeded_from')!r} at {manifest['seeded_at']}; "
                               "a namespace is seeded at most once — `hermes namespace reset` first")
    used = sorted(p.name for p in item.root.iterdir() if p.name != MANIFEST_NAME) if item.root.is_dir() else []
    if used:
        raise NamespaceRefused(Reason.NOT_FRESH, f"{item.id!r} already holds {used}; seed only at creation")


def seed(target_id: str, source: str, env: Mapping[str, str], *, dry_run: bool = False,
         with_memories: bool = False) -> dict[str, Any]:
    """Copy the allowlist from ``base`` or a NAMED namespace into a freshly created namespace, once.

    ``dry_run`` refuses exactly as the real seed would and returns its plan, writing nothing.
    ``with_memories`` (the owner's own reseed only) also copies each home's ``memories/``; it is
    refused unless the target is an account namespace (``acct-<16 hex>``), so a QA seed never carries it.
    """
    item = layout(target_id, env)
    if with_memories and not ACCOUNT_ID.fullmatch(item.id):
        raise NamespaceRefused(Reason.MEMORIES_NOT_ACCOUNT,
                               f"--with-memories seeds only an account namespace (acct-<16 hex>), not {item.id!r}")
    source = validate_id(source)
    if source == item.id:
        raise NamespaceRefused(Reason.SEED_SOURCE, "a namespace cannot seed itself")
    if source == BASE_ID:
        src_root = item.base_root
    else:
        src_item = existing_namespace(source, env)
        epoch_admitted(src_item, env)  # RT-STORE-EPOCH: never copy a shape this build cannot read
        src_root = src_item.root
    if not src_root.is_dir():
        raise NamespaceRefused(Reason.NOT_FOUND, f"the seed source {src_root} does not exist")
    bad = allowlist_violations(HOME_SEED + STORE_SEED + ROOT_SEED + SHARED_SEED)
    if bad:
        raise NamespaceRefused(Reason.SEED_SOURCE, f"the seed allowlist names never-seed entries {bad}; nothing copied")
    head = {"verb": "seed", "id": item.id, "from": source, "source_root": str(src_root), "root": str(item.root),
            "with_memories": with_memories}
    _assert_fresh(item, _namespace_manifest(item) or {})
    plan = plan_seed(src_root, item, with_memories=with_memories)  # every refusal lands before a write
    if dry_run:
        return {"ok": True, **head, "dry_run": True, **plan.payload()}
    ensure_manifest(item)
    manifest = _namespace_manifest(item) or {}
    _assert_fresh(item, manifest)
    with _exclusive(item):
        for src, dst, _rel in plan.copies:
            _copy(src, dst)
        write_instances(plan.instances)
    result = plan.payload()
    _write_manifest(item, restamped({
        **manifest, "seeded_from": source, "seeded_at": _now(), "seeded": result["copied"],
        "skipped": result["skipped"], "instances": [row["id"] for row in result["instances"]["carried"]],
        "with_memories": with_memories}))
    return {"ok": True, **head, "dry_run": False, **result}


