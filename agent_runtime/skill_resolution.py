"""Canonical shared-skill resolution, provenance and per-turn policy."""
import hashlib
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple
from hermes_constants import get_skills_dir
from agent_runtime.profile_home import CANONICAL_SHARED_SKILL_IDS, get_shared_skills_dir
from agent_runtime.skill_root_freshness import (
    TurnRootRegistries,
    needs_fresh_walk,
    registry_for_turn,
    walk_served_roots,
)

__layer__ = "stores"
# Import skill_utils only inside consumers: its compatibility aliases import us.

_SKILL_RUNTIME_SURFACE: ContextVar[str | None] = ContextVar(
    "hermes_skill_runtime_surface", default=None
)

_SKILL_RUNTIME_ROOT_NODE_MODE: ContextVar[bool] = ContextVar(
    "hermes_skill_runtime_root_node_mode", default=False
)

@contextmanager
def skill_runtime_scope(
    *, surface: str | None, root_node_mode: bool = False
) -> Iterator[None]:
    """Bind the active skill surface/mode for prompt and tool enforcement."""

    surface_token = _SKILL_RUNTIME_SURFACE.set(surface)
    mode_token = _SKILL_RUNTIME_ROOT_NODE_MODE.set(bool(root_node_mode))
    try:
        yield
    finally:
        _SKILL_RUNTIME_ROOT_NODE_MODE.reset(mode_token)
        _SKILL_RUNTIME_SURFACE.reset(surface_token)

def current_skill_runtime_context() -> tuple[str | None, bool]:
    """Return the active surface/mode, or ``(None, False)`` outside a lane."""

    return _SKILL_RUNTIME_SURFACE.get(), _SKILL_RUNTIME_ROOT_NODE_MODE.get()

def skill_runtime_snapshot_metadata(frontmatter: dict) -> dict:
    """Project the fork runtime metadata into the upstream skill snapshot."""
    metadata = frontmatter.get("metadata") if isinstance(frontmatter, dict) else {}
    hermes = metadata.get("hermes") if isinstance(metadata, dict) else {}
    runtime = {}
    if isinstance(hermes, dict):
        surfaces = hermes.get("surfaces") or []
        modes = hermes.get("modes") or []
        if not isinstance(surfaces, (str, list, tuple, set)):
            surfaces = []
        if not isinstance(modes, (str, list, tuple, set)):
            modes = []
        runtime = {
            "surfaces": [surfaces] if isinstance(surfaces, str) else list(surfaces),
            "modes": [modes] if isinstance(modes, str) else list(modes),
            "load_policy": str(hermes.get("load_policy") or "explicit"),
        }
    return runtime


def resolve_skill_runtime_defaults(
    skill_surface: str | None, skill_root_node_mode: bool | None,
) -> tuple[str | None, bool]:
    """Fill only unset prompt arguments from the current skill scope."""
    ambient_surface, ambient_mode = current_skill_runtime_context()
    if skill_surface is None:
        skill_surface = ambient_surface
    if skill_root_node_mode is None:
        skill_root_node_mode = ambient_mode
    return skill_surface, skill_root_node_mode


@dataclass(frozen=True, slots=True)
class SkillResolutionCandidate:
    """One filesystem skill candidate returned by the canonical resolver."""

    root: Path
    skill_dir: Path | None
    skill_md: Path
    source_kind: str

@dataclass(frozen=True, slots=True)
class SkillResolution:
    """Deterministic filesystem resolution for one skill identifier.

    ``status`` is one of ``resolved``, ``missing``, or ``collision``.  Callers
    must never choose a winner for a collision: the point of this result is to
    make the catalog, loader, readiness checks, and prompt receipts agree.
    """

    identifier: str
    status: str
    candidates: tuple[SkillResolutionCandidate, ...]

    @property
    def candidate(self) -> SkillResolutionCandidate | None:
        return self.candidates[0] if self.status == "resolved" else None

@dataclass(frozen=True, slots=True)
class _SkillRootRegistry:
    fingerprint: tuple[tuple[str, int | None, int | None], ...]
    manifests: tuple[tuple[Path | None, Path], ...]
    legacy: tuple[tuple[Path | None, Path], ...]
    manifests_by_alias: dict[str, tuple[tuple[Path | None, Path], ...]]
    legacy_by_alias: dict[str, tuple[tuple[Path | None, Path], ...]]
    #: ``manifests`` / ``legacy`` grouped by their file path, in registry order.
    #: ``resolve_skills`` asks "which entries ARE ``<root>/<name>/SKILL.md``"
    #: once per name; scanning the whole tuple for that was names x entries
    #: Path compares (~200 x ~1,150 per persona per snapshot build).
    manifests_by_path: dict[Path, tuple[tuple[Path | None, Path], ...]] = field(default_factory=dict)
    legacy_by_path: dict[Path, tuple[tuple[Path | None, Path], ...]] = field(default_factory=dict)
    #: ``realpath`` of an entry's file, filled on first ask. Valid exactly as
    #: long as the registry is: both are keyed on the root's signature.
    resolved_files: dict[Path, Path] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SkillRootManifest:
    skill_dir: Path | None
    manifest: Path
    aliases: frozenset[str]


def skill_root_manifests(root: Path) -> tuple[SkillRootManifest, ...]:
    """Public, signature-validated manifests and resolver aliases for one root."""
    registry = _skill_root_registry(root)
    aliases: dict[Path, set[str]] = {}
    for alias, entries in registry.manifests_by_alias.items():
        for _, manifest in entries:
            aliases.setdefault(manifest, set()).add(alias)
    return tuple(SkillRootManifest(directory, manifest, frozenset(aliases.get(manifest, ())))
                 for directory, manifest in registry.manifests)


def _group_by_path(
    entries: tuple[tuple[Path | None, Path], ...],
) -> dict[Path, tuple[tuple[Path | None, Path], ...]]:
    """Registry entries keyed by their file, order kept (``Path`` hash agrees with ``==``)."""

    grouped: dict[Path, list[tuple[Path | None, Path]]] = {}
    for entry in entries:
        grouped.setdefault(entry[1], []).append(entry)
    return {path: tuple(group) for path, group in grouped.items()}

_SKILL_ROOT_REGISTRY_CACHE: dict[str, _SkillRootRegistry] = {}

_SKILL_ROOT_REGISTRY_LOCK = threading.Lock()

_walk_state = threading.local()

def skill_root_walks_this_thread() -> int:
    """How many physical-root registry walks this thread has paid for."""

    return int(getattr(_walk_state, "walks", 0))

def reset_skill_root_walks_for_tests() -> None:
    """Test hook — zero this thread's walk counter."""

    _walk_state.walks = 0

def _note_skill_root_walk() -> None:
    _walk_state.walks = int(getattr(_walk_state, "walks", 0)) + 1

def skill_root_rebuilds_this_thread() -> int:
    """Registry REBUILDS (signature moved: candidates re-filtered, frontmatter
    re-read) this thread has paid for. A warm turn's answer is 0."""

    return int(getattr(_walk_state, "rebuilds", 0))

def _note_skill_root_rebuild() -> None:
    _walk_state.rebuilds = int(getattr(_walk_state, "rebuilds", 0)) + 1

#: h-chatperf: a turn-scoped ``_root_registries`` map for callers that cannot be
#: handed one. Upstream's ``skill_view`` resolves through ``resolve_skill`` with
#: no map, so a preload paid a second walk per root on top of the policy's own.
_SCOPED_ROOT_REGISTRIES: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "hermes_scoped_skill_root_registries", default=None
)

@contextmanager
def skill_root_registry_scope(registries: Optional[Dict[str, Any]]) -> Iterator[None]:
    """Let every resolve in this context share *registries* (no-op for ``None``).

    Bound only around a turn's pre-admit assembly, never around the model run,
    so a skill the agent writes mid-turn is still seen by its own next resolve.
    """

    if registries is None:
        yield
        return
    token = _SCOPED_ROOT_REGISTRIES.set(registries)
    try:
        yield
    finally:
        _SCOPED_ROOT_REGISTRIES.reset(token)

def _registries_for_call(explicit: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if explicit is not None:
        return explicit
    scoped = _SCOPED_ROOT_REGISTRIES.get()
    return scoped if scoped is not None else {}

def _skill_root_registry_cache_clear() -> None:
    """Test hook — drop reusable physical-root candidate registries."""

    with _SKILL_ROOT_REGISTRY_LOCK:
        _SKILL_ROOT_REGISTRY_CACHE.clear()

def _is_package_owned_markdown(path: Path, search_root: Path) -> bool:
    """True when a legacy Markdown candidate belongs to an ancestor directory skill."""
    try:
        relative = path.relative_to(search_root)
    except ValueError:
        return False
    return any(
        (search_root.joinpath(*relative.parts[:depth]) / "SKILL.md").is_file()
        for depth in range(1, len(relative.parts))
    )


def _listing(directory: str) -> list[os.DirEntry]:
    """One directory's entries, or none when it cannot be listed."""

    try:
        with os.scandir(directory) as entries:
            return list(entries)
    except OSError:
        return []


def _entry_stat(entry: os.DirEntry) -> tuple[int | None, int | None]:
    """(mtime_ns, size) from the listing (free on Windows), or (None, None)."""

    try:
        stat = entry.stat()
    except OSError:
        return None, None
    return stat.st_mtime_ns, stat.st_size


def _descend_following_links(entry: os.DirEntry, seen_links: set[str]) -> bool:
    """Walk into this directory? Symlinked ones are followed (as
    ``os.walk(followlinks=True)`` does) but once each, so a cycle ends."""

    try:
        if not entry.is_dir():
            return False
        if not entry.is_symlink():
            return True
    except OSError:
        return False
    real = os.path.realpath(entry.path)
    if real in seen_links:
        return False
    seen_links.add(real)
    return True


def _skill_root_signature(root: Path) -> tuple[tuple[str, int | None, int | None], ...]:
    """Every ``*.md`` under *root*, as (path, mtime_ns, size).

    The registry's validation key (h-chatperf, 2026-10-03). It used to be the
    registry's own candidate list -- ``iter_skill_index_files`` plus an
    ``rglob("*.md")`` filtered through ``is_skill_support_path`` and
    ``_is_package_owned_markdown`` (an ``exists()`` per ancestor per file) --
    stat'ed one path at a time: ~220 ms a root warm on the operator's ~1,150
    skill files, paid three to four times a turn and again per profile root in
    every snapshot build. This is one ``os.scandir`` walk whose stats come with
    the directory listing on Windows: ~15 ms a root.

    **Why it invalidates correctly.** It is a SUPERSET of everything the
    registry reads: every manifest and every legacy candidate is a ``*.md`` file
    under the root (this walk follows directory symlinks, as
    ``iter_skill_index_files`` does, and prunes nothing, as ``rglob`` does not),
    and the two filters only ask whether some ``SKILL.md`` exists -- also a
    ``*.md`` file here. Upstream retired org-token gating, so no non-markdown
    marker participates in the scan. An add, delete,
    rename or content write of any input moves this tuple; a change to a file
    the registry ignores costs one rebuild and nothing else.
    """
    stamps: list[tuple[str, int | None, int | None]] = []
    seen_links: set[str] = set()
    stack = [str(root)]
    while stack:
        for entry in _listing(stack.pop()):
            if _descend_following_links(entry, seen_links):
                stack.append(entry.path)
            elif entry.name.endswith(".md"):
                stamps.append((entry.path, *_entry_stat(entry)))
    stamps.sort()
    return tuple(stamps)


def _skill_root_registry(root: Path) -> _SkillRootRegistry:
    """Return the candidate registry for one physical skill root.

    Validated by :func:`_skill_root_signature` (every markdown file under the
    root). A changed root rebuilds only its own
    registry; unchanged roots reuse parsed frontmatter across profiles, turns
    and snapshot builds.

    **This function always touches the filesystem**, since h-chatperf only as
    one listing walk: the candidate filtering and the frontmatter reads run only
    when the signature moved. A caller that wants to avoid even the walk shares
    a ``_root_registries`` map for the life of one turn -- chat-turn-prep CP-5
    -- or binds one with :func:`skill_root_registry_scope`.
    """
    from agent import skill_utils as _skills

    _note_skill_root_walk()
    root_key = str(_resolved_path(root))
    if not root.is_dir():
        fingerprint: tuple[tuple[str, int | None, int | None], ...] = ()
        with _SKILL_ROOT_REGISTRY_LOCK:
            cached = _SKILL_ROOT_REGISTRY_CACHE.get(root_key)
            if cached is not None and cached.fingerprint == fingerprint:
                return cached
            registry = _SkillRootRegistry(fingerprint, (), (), {}, {})
            _SKILL_ROOT_REGISTRY_CACHE[root_key] = registry
            return registry

    # Taken BEFORE the candidates are read: a write landing during the rebuild
    # leaves the stored signature older than the content, so the next call
    # rebuilds again -- never the other way round.
    fingerprint = _skill_root_signature(root)
    with _SKILL_ROOT_REGISTRY_LOCK:
        cached = _SKILL_ROOT_REGISTRY_CACHE.get(root_key)
        if cached is not None and cached.fingerprint == fingerprint:
            return cached
    _note_skill_root_rebuild()

    manifests = list(_skills.iter_skill_index_files(root, "SKILL.md"))
    legacy = [
        path
        for path in root.rglob("*.md")
        if (path.name != "SKILL.md" and not _skills.is_skill_support_path(path)
            and not _is_package_owned_markdown(path, root))
    ]

    manifest_aliases: dict[str, list[tuple[Path | None, Path]]] = {}
    for manifest in manifests:
        aliases = {manifest.parent.name}
        # The one parser of a manifest (D1.05 CF-1): the compatibility pass reads
        # the same file through it, so a cold build parses each manifest once.
        frontmatter = _cached_skill_frontmatter(manifest)
        declared = str(frontmatter.get("name") or "").strip()
        if declared:
            aliases.add(declared)
        for alias in aliases:
            manifest_aliases.setdefault(alias, []).append((manifest.parent, manifest))

    legacy_aliases: dict[str, list[tuple[Path | None, Path]]] = {}
    for path in legacy:
        legacy_aliases.setdefault(path.stem, []).append((None, path))

    manifest_entries = tuple((manifest.parent, manifest) for manifest in manifests)
    legacy_entries = tuple((None, path) for path in legacy)
    registry = _SkillRootRegistry(
        fingerprint,
        manifest_entries,
        legacy_entries,
        {key: tuple(value) for key, value in manifest_aliases.items()},
        {key: tuple(value) for key, value in legacy_aliases.items()},
        _group_by_path(manifest_entries),
        _group_by_path(legacy_entries),
    )
    with _SKILL_ROOT_REGISTRY_LOCK:
        _SKILL_ROOT_REGISTRY_CACHE[root_key] = registry
    return registry

def _resolved_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError):
        return path.expanduser().absolute()

#: ``skill_search_roots`` memo: key -> (roots, create_dir, create_dir existed).
_SEARCH_ROOTS_CACHE: Dict[Tuple[Any, ...], Tuple[Tuple[Path, ...], Optional[Path], bool]] = {}

_SEARCH_ROOTS_CACHE_MAX = 64


def _search_roots_cache_clear() -> None:
    """Test hook — drop the ``skill_search_roots`` memo."""

    _SEARCH_ROOTS_CACHE.clear()


def skill_search_roots() -> List[Path]:
    """``agent.skill_utils.get_all_skills_dirs()`` for the active profile, memoized per profile.

    h-readiness: upstream parses ``config.yaml`` behind a ONE-entry cache that
    clears on every new key, which is right for a process with one
    ``HERMES_HOME`` and wrong for this one. A snapshot build binds each
    persona's profile in turn, so every persona re-parsed its profile's config
    (~60 ms of ruamel each, 5 of them per build on the operator's roster).

    The key is every input the upstream body reads: the walker itself (a patch
    or reload invalidates), the active Hermes home (skills dir, config path,
    relative-path anchor, shared root), ``config.yaml``'s file signature, and
    the whole environment (``${VAR}``/``~`` expansion, ``HERMES_SHARED_SKILLS``).
    The one filesystem fact it adds, whether the configured ``create_dir``
    exists, is re-checked on every hit. ``external_dirs`` existence is upstream's
    own cache's contract (keyed on the config signature alone) and is served
    exactly as upstream would serve it.
    """
    from agent import skill_utils as _skills
    from hermes_constants import get_hermes_home
    from utils import file_signature

    home = get_hermes_home()
    try:
        config_sig: Optional[Tuple[int, ...]] = file_signature((home / "config.yaml").stat())
    except OSError:
        config_sig = None
    key = (
        _skills.get_all_skills_dirs,
        str(home),
        config_sig,
        frozenset(os.environ.items()),
    )
    cached = _SEARCH_ROOTS_CACHE.get(key)
    if cached is not None:
        roots, create_dir, existed = cached
        if create_dir is None or create_dir.is_dir() == existed:
            return list(roots)
    create_dir = _skills.get_skill_create_dir()
    existed = create_dir is not None and create_dir.is_dir()
    roots = tuple(_skills.get_all_skills_dirs())
    if len(_SEARCH_ROOTS_CACHE) >= _SEARCH_ROOTS_CACHE_MAX:
        _SEARCH_ROOTS_CACHE.clear()
    _SEARCH_ROOTS_CACHE[key] = (roots, create_dir, existed)
    return list(roots)


def skill_source_kind(root: Path) -> str:
    """Classify a resolver root without exposing its absolute path on wire."""

    resolved = _resolved_path(root)
    if resolved == _resolved_path(get_skills_dir()):
        return "profile_local"
    if resolved == _resolved_path(get_shared_skills_dir()):
        return "shared_core"
    return "external"

def resolve_skill(
    identifier: str,
    *,
    roots: List[Path] | None = None,
    categorized_identifier: str | None = None,
    _root_registries: Dict[str, _SkillRootRegistry] | None = None,
) -> SkillResolution:
    """Resolve a filesystem skill through the one ordered runtime registry.

    Plugin-qualified skills remain owned by the plugin registry.  This function
    owns every filesystem skill lookup, including direct/nested/frontmatter-name
    and legacy flat-file forms.  Duplicate candidates produce ``collision``;
    root ordering is descriptive only and never silently selects a winner.
    """
    from agent import skill_utils as _skills

    name = str(identifier or "").strip()
    search_roots = list(roots) if roots is not None else skill_search_roots()
    candidates: list[SkillResolutionCandidate] = []
    seen: set[Path] = set()

    def record(root: Path, skill_dir: Path | None, skill_md: Path) -> None:
        key = _resolved_path(skill_md)
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            SkillResolutionCandidate(
                root=root,
                skill_dir=skill_dir,
                skill_md=skill_md,
                source_kind=skill_source_kind(root),
            )
        )

    lookup_names = [name]
    categorized = str(categorized_identifier or "").strip()
    if categorized and categorized not in lookup_names:
        lookup_names.append(categorized)

    # chat-turn-prep CP-5: the same in/out accumulator ``resolve_skills`` takes.
    # This function is called ONCE PER NAME by the observability row's
    # ``_resolved_skill_receipt``, so without a shared map a turn pays one full
    # per-root walk for every used, queued and required-preload skill it names —
    # inside the very span the CP-9 read measured at 157–547 ms. The plan's §0.3
    # counted three walkers; this was the fourth.
    root_registries = _registries_for_call(_root_registries)

    for root in search_roots:
        root_key = str(_resolved_path(root))
        registry = _registry_in(root_registries, root, root_key)
        for lookup in lookup_names:
            direct_manifest = root / lookup / "SKILL.md"
            for skill_dir, manifest in registry.manifests:
                if manifest == direct_manifest:
                    record(root, skill_dir, manifest)
            direct_legacy = (root / lookup).with_suffix(".md")
            for skill_dir, legacy in registry.legacy:
                if legacy == direct_legacy:
                    record(root, skill_dir, legacy)
        for skill_dir, manifest in registry.manifests_by_alias.get(name, ()):
            record(root, skill_dir, manifest)
        for skill_dir, legacy in registry.legacy_by_alias.get(name, ()):
            record(root, skill_dir, legacy)

    status = _skill_resolution_status(name, candidates)
    resolution = SkillResolution(name, status, tuple(candidates))
    if needs_fresh_walk(root_registries, {name: resolution}):
        walk_served_roots(root_registries)
        return resolve_skill(identifier, roots=roots, categorized_identifier=categorized_identifier,
                             _root_registries=root_registries)
    return resolution

def _registry_in(root_registries: Dict[str, Any], root: Path, root_key: str) -> _SkillRootRegistry:
    """``root``'s registry from the caller's map, else read once and kept there.

    h-warm-phases: a turn's pre-admit map (``TurnRootRegistries``) reads the process cache and
    queues the root for a re-walk after ``request_sent``; every other map walks.
    """

    registry = root_registries.get(root_key)
    if registry is None:
        if isinstance(root_registries, TurnRootRegistries):
            registry = registry_for_turn(root, root_key, root_registries)
        else:
            registry = _skill_root_registry(root)
        root_registries[root_key] = registry
    return registry

def resolve_skills(
    identifiers: List[str],
    *,
    roots: List[Path] | None = None,
    _root_registries: Dict[str, _SkillRootRegistry] | None = None,
) -> Dict[str, SkillResolution]:
    """Resolve many bare/path identifiers with one registry walk."""
    from agent import skill_utils as _skills

    names = list(dict.fromkeys(str(item or "").strip() for item in identifiers))
    names = [name for name in names if name]
    search_roots = list(roots) if roots is not None else skill_search_roots()
    found: Dict[str, list[SkillResolutionCandidate]] = {name: [] for name in names}
    seen: Dict[str, set[Path]] = {name: set() for name in names}
    root_registries = _registries_for_call(_root_registries)
    # h-readiness: ``record`` paid a ``realpath`` per candidate (a syscall pair
    # on Windows) and re-classified the root per candidate. The realpath now
    # lives on the registry it came from; the root's kind is classified once.

    def record(
        name: str,
        root: Path,
        kind: str,
        resolved_files: Dict[Path, Path],
        skill_dir: Path | None,
        skill_md: Path,
    ) -> None:
        key = resolved_files.get(skill_md)
        if key is None:
            key = resolved_files[skill_md] = _resolved_path(skill_md)
        if key in seen[name]:
            return
        seen[name].add(key)
        found[name].append(
            SkillResolutionCandidate(
                root=root,
                skill_dir=skill_dir,
                skill_md=skill_md,
                source_kind=kind,
            )
        )

    for root in search_roots:
        root_key = str(_resolved_path(root))
        registry = _registry_in(root_registries, root, root_key)
        kind = skill_source_kind(root)
        hit = registry.resolved_files
        for name in names:
            for skill_dir, manifest in registry.manifests_by_path.get(root / name / "SKILL.md", ()):
                record(name, root, kind, hit, skill_dir, manifest)
            for skill_dir, legacy in registry.legacy_by_path.get((root / name).with_suffix(".md"), ()):
                record(name, root, kind, hit, skill_dir, legacy)
            for skill_dir, manifest in registry.manifests_by_alias.get(name, ()):
                record(name, root, kind, hit, skill_dir, manifest)
            for skill_dir, legacy in registry.legacy_by_alias.get(name, ()):
                record(name, root, kind, hit, skill_dir, legacy)

    result: Dict[str, SkillResolution] = {}
    for name, candidates in found.items():
        status = _skill_resolution_status(name, candidates)
        result[name] = SkillResolution(name, status, tuple(candidates))
    if needs_fresh_walk(root_registries, result):
        walk_served_roots(root_registries)
        return resolve_skills(identifiers, roots=roots, _root_registries=root_registries)
    return result

def _skill_resolution_status(
    identifier: str, candidates: list[SkillResolutionCandidate]
) -> str:
    if not candidates:
        return "missing"
    if len(candidates) != 1:
        return "collision"
    if (
        identifier in CANONICAL_SHARED_SKILL_IDS
        and candidates[0].source_kind != "shared_core"
    ):
        return "invalid_source"
    return "resolved"

_CONTENT_HASH_CACHE: Dict[Tuple[Any, ...], str] = {}

_CONTENT_HASH_CACHE_MAX = 4096

def _content_hash_cache_clear() -> None:
    """Test hook — drop the skill package content-hash cache."""
    _CONTENT_HASH_CACHE.clear()

def _package_file_stamps(
    skill_dir: Path,
) -> list[tuple[str, Path, int | None, int | None]]:
    """The package's hashed files as (relative, path, mtime_ns, size), in hash order.

    h-chatperf: the same file SET and the same ORDER as the
    ``sorted(skill_dir.rglob("*"))`` + ``is_file()`` + per-path ``stat()`` this
    replaced -- the digest depends on both, and install receipts compare it --
    but one ``os.scandir`` walk, whose stats come with the listing on Windows.
    ~2.2 ms a package warm before, paid per accessible skill on every chat turn's
    observability row.

    Equivalences, each deliberate: a directory is descended only when it is a
    real directory (``rglob`` does not follow directory symlinks); a file is
    kept when ``is_file()`` holds through a symlink (as ``Path.is_file`` does);
    a name starting with ``.`` or in ``EXCLUDED_SKILL_DIRS`` drops everything
    beneath it (the old filter rejected any path with such a PART); and the
    final order is ``sorted()`` over the same ``Path`` objects.
    """
    from agent import skill_utils as _skills

    excluded = _skills.EXCLUDED_SKILL_DIRS
    found: list[tuple[Path, tuple[str, ...], int | None, int | None]] = []
    stack: list[tuple[str, tuple[str, ...]]] = [(str(skill_dir), ())]
    while stack:
        directory, prefix = stack.pop()
        for entry in _listing(directory):
            if entry.name.startswith(".") or entry.name in excluded:
                continue
            parts = (*prefix, entry.name)
            kind = _package_entry_kind(entry)
            if kind == "dir":
                stack.append((entry.path, parts))
            elif kind == "file":
                found.append((Path(entry.path), parts, *_entry_stat(entry)))
    found.sort(key=lambda item: item[0])
    return [("/".join(parts), path, mtime, size) for path, parts, mtime, size in found]


def _package_entry_kind(entry: os.DirEntry) -> str:
    """``dir`` (a real directory, never a symlinked one -- ``rglob`` does not
    follow them), ``file`` (``is_file`` through a symlink), else ``skip``."""

    try:
        if entry.is_dir(follow_symlinks=False):
            return "dir"
        return "file" if entry.is_file() else "skip"
    except OSError:
        return "skip"


def skill_package_content_hash(skill_dir: Path | None, skill_md: Path) -> str:
    """Stable content hash for the exact skill package the resolver selected.

    mtime-cached (see ``_CONTENT_HASH_CACHE``): the returned digest is identical
    to an uncached run; repeats within a build skip re-reading unchanged files.
    """
    if skill_dir is None:
        base = skill_md.parent
        try:
            relative = "/".join(skill_md.relative_to(base).parts)
        except ValueError:
            relative = skill_md.name
        try:
            st = skill_md.stat()
            stamped = [(relative, skill_md, st.st_mtime_ns, st.st_size)]
        except OSError:
            stamped = [(relative, skill_md, None, None)]
    else:
        base = skill_dir
        stamped = _package_file_stamps(skill_dir)

    entries: list[tuple[str, Path]] = [(relative, source) for relative, source, _m, _s in stamped]
    stamps = [(relative, mtime, size) for relative, _source, mtime, size in stamped]
    cache_key = (str(base), tuple(stamps))
    cached = _CONTENT_HASH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    digest = hashlib.sha256()
    for relative, source in entries:
        digest.update(relative.encode("utf-8", errors="replace"))
        digest.update(b"\x00")
        try:
            digest.update(source.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\x00")
    value = digest.hexdigest()
    if len(_CONTENT_HASH_CACHE) >= _CONTENT_HASH_CACHE_MAX:
        _CONTENT_HASH_CACHE.clear()
    _CONTENT_HASH_CACHE[cache_key] = value
    return value

def skill_frontmatter_runtime_compatibility(
    frontmatter: dict[str, Any] | None,
    *,
    surface: str,
    root_node_mode: bool = False,
) -> dict[str, Any]:
    """Evaluate surface/mode compatibility from parsed skill frontmatter."""

    frontmatter = frontmatter if isinstance(frontmatter, dict) else {}
    metadata = frontmatter.get("metadata") if isinstance(frontmatter, dict) else {}
    hermes = metadata.get("hermes") if isinstance(metadata, dict) else {}
    if not isinstance(hermes, dict):
        # A skill authored for another runtime (metadata present, hermes block
        # absent or None) must degrade to defaults; this function runs for every
        # skill in the shared root on every prompt-observability build, so one
        # foreign manifest must not take down the whole lane.
        hermes = {}
    surfaces = hermes.get("surfaces")
    modes = hermes.get("modes")
    if isinstance(surfaces, str):
        surfaces = [surfaces]
    elif not isinstance(surfaces, (list, tuple, set)):
        surfaces = []
    if isinstance(modes, str):
        modes = [modes]
    elif not isinstance(modes, (list, tuple, set)):
        modes = []
    allowed_surfaces = {str(item) for item in surfaces or []}
    allowed_modes = {str(item) for item in modes or []}
    load_policy = str(hermes.get("load_policy") or "explicit")
    if allowed_surfaces and surface not in allowed_surfaces:
        return {
            "compatible": False,
            "reason": "surface_not_supported",
            "load_policy": load_policy,
        }
    active_mode = "root_node" if root_node_mode else "standard"
    if allowed_modes and active_mode not in allowed_modes:
        return {
            "compatible": False,
            "reason": "mode_not_supported",
            "load_policy": load_policy,
        }
    return {
        "compatible": True,
        "reason": "compatible",
        "surface": surface,
        "mode": active_mode,
        "load_policy": load_policy,
    }

def _cached_skill_frontmatter(skill_md: Path) -> Dict[str, Any]:
    """mtime-cached frontmatter parse for a SKILL.md manifest.

    ``skill_runtime_compatibility`` is evaluated per skill, per surface, per
    persona across a snapshot build (~12.9k ``_skills.parse_frontmatter`` calls / ~3.8s
    measured 2026-07-23), yet a manifest's bytes only change when the file
    changes on disk. Cache the (read_text + _skills.parse_frontmatter) by the file's
    identity+mtime+size (``parse_cache.cached_by_mtime``) so repeats within a
    build are free while an on-disk edit invalidates the entry. Behavior is
    identical to the inline parse on a cache miss; the result is read-only, never
    mutated, so sharing the cached dict is safe.
    """
    from agent import skill_utils as _skills
    from agent_runtime.parse_cache import cached_by_mtime

    def _load(path: Path) -> Dict[str, Any]:
        frontmatter, _ = _skills.parse_frontmatter(path.read_text(encoding="utf-8"))
        return frontmatter if isinstance(frontmatter, dict) else {}

    return cached_by_mtime(skill_md, _load, default={})

def skill_runtime_compatibility(
    candidate: SkillResolutionCandidate | None,
    *,
    surface: str,
    root_node_mode: bool = False,
    preparation_epoch=None,
) -> dict[str, Any]:
    """Evaluate declared surface/mode compatibility for a resolved skill."""

    if candidate is None:
        return {"compatible": False, "reason": "unresolved"}
    frontmatter = (preparation_epoch.frontmatter(candidate.skill_md)
                   if preparation_epoch is not None else _cached_skill_frontmatter(candidate.skill_md))
    return skill_frontmatter_runtime_compatibility(
        frontmatter,
        surface=surface,
        root_node_mode=root_node_mode,
    )

def required_preload_skill_ids(
    identifiers: List[str],
    *,
    surface: str,
    root_node_mode: bool = False,
    _root_registries: Dict[str, _SkillRootRegistry] | None = None,
) -> List[str]:
    """Return assigned skills whose resolved policy requires model loading.

    ``_root_registries`` is chat-turn-prep CP-5's shared walk: the mission-chat
    handler hands the same map to this call and to the prompt-observability
    resolver, so the preload policy and the observability row are answered from
    ONE registry snapshot per physical root per turn instead of one each.
    """

    names = list(dict.fromkeys(str(item or "").strip() for item in identifiers))
    names = [name for name in names if name]
    resolutions = resolve_skills(names, _root_registries=_root_registries)
    required: List[str] = []
    for name in names:
        resolution = resolutions[name]
        compatibility = skill_runtime_compatibility(
            resolution.candidate,
            surface=surface,
            root_node_mode=root_node_mode,
            preparation_epoch=(_root_registries.preparation_epoch
                               if isinstance(_root_registries, TurnRootRegistries) else None),
        )
        if (
            resolution.status == "resolved"
            and compatibility.get("compatible")
            and compatibility.get("load_policy") == "required_preload"
        ):
            required.append(name)
    return required
