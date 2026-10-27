"""Machine-local root registry + the single config path-token chokepoint.

Why this exists
---------------
Profile ``config.yaml`` files reference on-disk locations of *other* checkouts —
the EterniaLauncher repo, the backend repo, a helper script inside one of them.
Stored as absolute paths (``X:\\Unreal Engine\\...``) those entries are unusable
on a second machine and on any non-Windows OS. Storing them *relative to the
Hermes install* does not help: the relative distance between the Hermes home and
an unrelated checkout is MORE machine-specific, not less.

The portable shape is the split the harness already uses for MCP capability vs.
MCP binding (persona ``required_mcp_servers`` is the portable capability;
``mcp_servers.<name>.command`` is the machine binding):

* the CONFIG names a LOGICAL root plus a repo-relative tail —
  ``${roots.eternia_launcher}/tool/.../stagec_qa_mcp_server${exe_suffix}``.
  That text is byte-identical on every machine and is what realm sync carries.
* THIS MACHINE binds each logical root to an absolute local path in
  ``machine_roots.json`` — a registry that is never synced (it is hard-excluded
  from realm sync exactly like ``auth.json`` and ``state.db``).

Guarantees
----------
* **One expansion chokepoint.** :func:`expand_config_paths` and
  :func:`path_token_issues` are thin wrappers over a single private walker;
  nothing else in the tree expands these tokens.
* **Correct separators everywhere.** Tails are split on ``/`` *and* ``\\`` and
  re-joined with :meth:`pathlib.Path.joinpath`, never by concatenating a
  hardcoded separator.
* **Never a fabricated path.** An unbound root, or a root bound to a path that
  does not exist, produces a typed :class:`PathTokenIssue` that rides the
  existing readiness/preflight lanes. There is no default root, no "best
  effort" join, and no silent drop.
* **Backward compatible.** A value with no ``${roots.…}`` / ``${exe_suffix}``
  token is returned unchanged — expansion is a no-op for every plain absolute
  path already in a config today.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any

from hermes_constants import get_default_hermes_root, get_hermes_home

__layer__ = "models"

logger = logging.getLogger(__name__)


MACHINE_ROOTS_FILENAME = "machine_roots.json"
#: Schema 3 names the two halves (plan ``machine-roots-two-halves-2026-10-26.md`` §2.1): ``config_roots``
#: (what ``${roots.<name>}`` expands to) and ``slot_folders`` (``{workspace: {slot: path}}``), and keeps
#: writing ``roots`` / ``workspace_roots`` as mirrors for an edition that reads schema 2. Readers prefer
#: the new keys and fall back to the old.
MACHINE_ROOTS_SCHEMA_VERSION = 3
#: A registry whose ``roots`` may still hold slot mirrors (the retired ``setdefault``): upgraded once by
#: ``workspace_slots.scoped_roots`` to schema 3, dropping each mirror of a single slot binding.
MACHINE_ROOTS_MIRRORED_SCHEMA_VERSION = 2
#: A registry written before workspace-scoped slot roots (no ``workspace_roots`` map): upgraded once by
#: ``workspace_slots`` on its first read (plan work-slot-roots-per-workspace-2026-10-21 §2).
MACHINE_ROOTS_LEGACY_SCHEMA_VERSION = 1

# ``${roots.<name>}`` — the logical-root token.
ROOT_TOKEN_RE = re.compile(r"\$\{roots\.([^}]*)\}")
# ``${exe_suffix}`` — ``.exe`` on Windows, empty elsewhere.
EXE_SUFFIX_TOKEN = "${exe_suffix}"
_ROOT_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

# A ``${roots.X}`` token is followed by a path tail that we must re-join with
# native separators. The tail ends at the first character that cannot belong to
# a path *in a config value* — whitespace, a quote, a shell metacharacter, or
# the start of another token. This is what lets a root token sit inside a
# larger command string (``Set-Location '${roots.x}'; dart mcp-server``) and
# still have only its path part normalized.
_TAIL_TERMINATORS = frozenset(" \t\r\n'\"`;|&<>,()$")

ISSUE_UNBOUND_ROOT = "unbound_root"
ISSUE_ROOT_TARGET_MISSING = "root_target_missing"
#: A name only slot folders bind, read with no workspace that binds it, and two workspaces bind it to
#: different folders: nothing resolves (never first-wins). Plan machine-roots-two-halves §2.3.
ISSUE_ROOT_AMBIGUOUS = "root_ambiguous"
ISSUE_INVALID_ROOT_TOKEN = "invalid_root_token"
ISSUE_INVALID_REGISTRY = "invalid_registry"
ISSUE_PLATFORM_UNSUPPORTED = "platform_unsupported"
# A configured MCP block that does not match its canonical template.
#
# BLOCKING since 2026-08-01 (operator ruling). It was advisory for exactly one
# window — while live configs still carried the drift this describes, so that
# reporting it could not call a running profile broken before anyone had been
# given the chance to fix it. The rationale for the flip: a drifted block
# "works" solely because some OTHER repo happens to carry a fallback for the
# field it omits — agreement by coincidence, which is exactly the failure mode
# that stays invisible until the fallback moves. Every code in this module now
# means the same thing: this declaration is not usable as written, and readiness
# must say so. Reporting stays report-only — nothing here rewrites a config.
ISSUE_MCP_TEMPLATE_DRIFT = "mcp_server_template_drift"

PLATFORM_WINDOWS = "windows"
PLATFORM_MACOS = "macos"
PLATFORM_LINUX = "linux"

_PLATFORM_ALIASES = {
    "windows": PLATFORM_WINDOWS,
    "win": PLATFORM_WINDOWS,
    "win32": PLATFORM_WINDOWS,
    "nt": PLATFORM_WINDOWS,
    "macos": PLATFORM_MACOS,
    "mac": PLATFORM_MACOS,
    "osx": PLATFORM_MACOS,
    "darwin": PLATFORM_MACOS,
    "linux": PLATFORM_LINUX,
    "posix": PLATFORM_LINUX,
}


@dataclass(frozen=True, slots=True)
class PathTokenIssue:
    """One typed reason a config path field could not be resolved."""

    code: str
    summary: str
    fix_hint: str
    field: str = ""
    root_name: str = ""

    def row(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field": self.field,
            "root_name": self.root_name,
            "summary": self.summary,
            "fix_hint": self.fix_hint,
        }


class MachineRootError(RuntimeError):
    """Raised by the strict expansion form when a path token cannot resolve."""

    def __init__(self, issues: list[PathTokenIssue]):
        self.issues = list(issues)
        super().__init__("; ".join(issue.summary for issue in self.issues) or "path token unresolved")

    @property
    def code(self) -> str:
        return self.issues[0].code if self.issues else ISSUE_UNBOUND_ROOT

    @property
    def summary(self) -> str:
        return "; ".join(issue.summary for issue in self.issues) or "path token unresolved"

    @property
    def fix_hint(self) -> str:
        return self.issues[0].fix_hint if self.issues else ""

    def rows(self) -> list[dict[str, Any]]:
        return [issue.row() for issue in self.issues]


@dataclass(frozen=True, slots=True)
class MachineRoots:
    """The resolved logical-root -> absolute-local-path bindings for this machine."""

    roots: dict[str, str] = dataclass_field(default_factory=dict)
    sources: tuple[str, ...] = ()
    issues: tuple[PathTokenIssue, ...] = ()
    #: A slot's machine fill PER WORKSPACE (file key ``slot_folders``): ``{workspace_id: {slot: abs path}}``.
    #: The ``${roots.<name>}`` expansion reads it only for a name ``roots`` (``config_roots``) lacks.
    workspace_roots: Mapping[str, Mapping[str, str]] = dataclass_field(default_factory=dict)
    #: The write target's schema: 1 with no slot map, 2 while its ``roots`` may hold slot mirrors, else 3.
    schema_version: int = MACHINE_ROOTS_SCHEMA_VERSION

    def get(self, name: str) -> Path | None:
        raw = self.roots.get(name)
        return Path(raw) if raw else None

    def workspace_root(self, workspace_id: str, slot: str) -> Path | None:
        raw = (self.workspace_roots.get(workspace_id) or {}).get(slot)
        return Path(raw) if raw else None

    def slot_folder_bindings(self, name: str) -> dict[str, str]:
        """``{workspace_id: path}`` for every workspace whose slot ``name`` is bound on this machine."""

        return {ws: str(slots[name]) for ws, slots in sorted(self.workspace_roots.items()) if slots.get(name)}

    def names(self) -> list[str]:
        return sorted(self.roots)

    def row(self) -> dict[str, Any]:
        return {
            "schema_version": MACHINE_ROOTS_SCHEMA_VERSION,
            "roots": {name: self.roots[name] for name in sorted(self.roots)},
            "workspace_roots": _sorted_workspace_roots(self.workspace_roots),
            "sources": list(self.sources),
            "issues": [issue.row() for issue in self.issues],
        }


# ── Platform ────────────────────────────────────────────────────────────────


def current_platform_key() -> str:
    """This process's platform, normalized to the config vocabulary."""

    platform = sys.platform
    if platform.startswith("win"):
        return PLATFORM_WINDOWS
    if platform == "darwin":
        return PLATFORM_MACOS
    return PLATFORM_LINUX


def exe_suffix() -> str:
    """Executable suffix for this platform (``.exe`` on Windows, else empty)."""

    return ".exe" if current_platform_key() == PLATFORM_WINDOWS else ""


def normalize_platforms(platforms: Any) -> list[str]:
    if platforms is None:
        return []
    if isinstance(platforms, str):
        raw: Iterable[Any] = [platforms]
    elif isinstance(platforms, (list, tuple, set, frozenset)):
        raw = platforms
    else:
        return []
    normalized: list[str] = []
    for item in raw:
        key = _PLATFORM_ALIASES.get(str(item or "").strip().lower())
        if key and key not in normalized:
            normalized.append(key)
    return normalized


def platform_supported(platforms: Any) -> bool:
    """True when an entry declaring ``platforms`` may run on this machine.

    An entry with no declaration is platform-agnostic and always supported —
    that keeps every config written before this feature working unchanged.
    """

    declared = normalize_platforms(platforms)
    if not declared:
        return True
    return current_platform_key() in declared


# ── Registry ────────────────────────────────────────────────────────────────


def machine_roots_registry_paths() -> tuple[Path, ...]:
    """Registry lookup order: machine-wide first, then a per-profile override.

    The machine-wide file lives beside the profiles directory because the
    bindings describe THIS MACHINE, not one profile's preferences — every
    profile on the box resolves ``${roots.eternia_launcher}`` to the same
    checkout. A per-profile file is still honoured (per-key override) so a
    profile can be pointed at a different checkout without disturbing the rest.
    """

    paths: list[Path] = []
    for candidate in (get_default_hermes_root() / MACHINE_ROOTS_FILENAME, get_hermes_home() / MACHINE_ROOTS_FILENAME):
        if candidate not in paths:
            paths.append(candidate)
    return tuple(paths)


_roots_cache: dict[tuple[Any, ...], MachineRoots] = {}


def machine_roots_cache_clear() -> None:
    """Test hook — drop the registry read memo."""

    _roots_cache.clear()


def _registry_stamp(path: Path) -> tuple[Any, ...]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def load_machine_roots(*, refresh: bool = False) -> MachineRoots:
    """Read the machine-root registry (memoized on file mtime/size)."""

    paths = machine_roots_registry_paths()
    key = tuple(_registry_stamp(path) for path in paths)
    if not refresh:
        cached = _roots_cache.get(key)
        if cached is not None:
            return cached
    roots: dict[str, str] = {}
    scoped: dict[str, dict[str, str]] = {}
    sources: list[str] = []
    issues: list[PathTokenIssue] = []
    schema = MACHINE_ROOTS_SCHEMA_VERSION
    for index, path in enumerate(paths):
        parsed, parse_issues = _read_registry_file(path)
        issues.extend(parse_issues)
        if parsed is None:
            continue
        sources.append(str(path))
        roots.update(parsed.roots)
        for workspace_id, slots in parsed.workspace_roots.items():
            scoped.setdefault(workspace_id, {}).update(slots)
        if index == 0:
            schema = parsed.schema
    resolved = MachineRoots(roots=roots, sources=tuple(sources), issues=tuple(issues), workspace_roots=scoped,
                            schema_version=schema)
    _roots_cache[key] = resolved
    return resolved


@dataclass(frozen=True, slots=True)
class _RegistryFile:
    roots: dict[str, str]
    workspace_roots: dict[str, dict[str, str]]
    #: The file carries a slot-folder object (``slot_folders`` or ``workspace_roots``), even an empty one.
    scoped: bool
    #: 3 when it carries both named halves, 2 when only the mirrored keys, 1 with no slot map.
    schema: int = MACHINE_ROOTS_SCHEMA_VERSION


def _sorted_workspace_roots(scoped: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, str]]:
    return {ws: {slot: str(scoped[ws][slot]) for slot in sorted(scoped[ws])} for ws in sorted(scoped) if scoped[ws]}


def _read_workspace_roots(node: Any, path: Path, issues: list[PathTokenIssue]) -> dict[str, dict[str, str]]:
    """``workspace_roots``: a workspace key round-trips ``paths.safe_path_token``; a slot key is a root name."""

    from .paths import safe_path_token

    parsed: dict[str, dict[str, str]] = {}
    for workspace_id, slots in (node or {}).items() if isinstance(node, dict) else ():
        key = str(workspace_id or "").strip()
        if not key or safe_path_token(key) != key or not isinstance(slots, dict):
            issues.append(PathTokenIssue(code=ISSUE_INVALID_REGISTRY, root_name=key,
                                         summary=f"Workspace roots key '{key}' is not a workspace id ({path})",
                                         fix_hint="Re-bind the workspace's slots through Locate."))
            continue
        inner, inner_issues = _read_roots_node(slots, path)
        issues.extend(inner_issues)
        if inner:
            parsed[key] = inner
    return parsed


def _read_registry_file(path: Path) -> tuple[_RegistryFile | None, list[PathTokenIssue]]:
    if not path.is_file():
        return None, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [
            PathTokenIssue(
                code=ISSUE_INVALID_REGISTRY,
                summary=f"Machine root registry is unreadable ({type(exc).__name__}): {path}",
                fix_hint=f"Repair or delete {path}, then re-run `hermes harness roots list`.",
            )
        ]
    named = isinstance(payload, dict) and isinstance(payload.get("config_roots"), dict)
    node = payload.get("config_roots" if named else "roots") if isinstance(payload, dict) else None
    if not isinstance(node, dict):
        return None, [
            PathTokenIssue(
                code=ISSUE_INVALID_REGISTRY,
                summary=f"Machine root registry has no 'roots' object: {path}",
                fix_hint=f"Rewrite {path} as {{\"schema_version\": 2, \"roots\": {{...}}}}.",
            )
        ]
    parsed, issues = _read_roots_node(node, path)
    slot_key = "slot_folders" if isinstance(payload.get("slot_folders"), dict) else "workspace_roots"
    scoped = slot_key in payload
    workspace_roots = _read_workspace_roots(payload.get(slot_key), path, issues) if scoped else {}
    if named and slot_key == "slot_folders":
        schema = MACHINE_ROOTS_SCHEMA_VERSION
    else:
        schema = MACHINE_ROOTS_MIRRORED_SCHEMA_VERSION if scoped else MACHINE_ROOTS_LEGACY_SCHEMA_VERSION
    return _RegistryFile(parsed, workspace_roots, scoped, schema), issues


def _read_roots_node(node: Mapping[str, Any], path: Path) -> tuple[dict[str, str], list[PathTokenIssue]]:
    parsed: dict[str, str] = {}
    issues: list[PathTokenIssue] = []
    for name, value in node.items():
        clean = str(name or "").strip()
        text = str(value or "").strip()
        if not _ROOT_NAME_RE.match(clean):
            issues.append(
                PathTokenIssue(
                    code=ISSUE_INVALID_REGISTRY,
                    root_name=clean,
                    summary=f"Machine root name '{clean}' is not [A-Za-z0-9_]+ ({path})",
                    fix_hint="Rename the root to letters, digits, and underscores only.",
                )
            )
            continue
        if not text:
            issues.append(
                PathTokenIssue(
                    code=ISSUE_INVALID_REGISTRY,
                    root_name=clean,
                    summary=f"Machine root '{clean}' is bound to an empty path ({path})",
                    fix_hint=f"hermes harness roots set {clean} <absolute-path> --yes",
                )
            )
            continue
        parsed[clean] = text
    return parsed, issues


def _held_registry(target: Path) -> _RegistryFile | None:
    held, _ = _read_registry_file(target)
    return held


def legacy_roots_mirror(
    config_roots: Mapping[str, str], slot_folders: Mapping[str, Mapping[str, str]]
) -> dict[str, str]:
    """The schema-2 ``roots`` an older edition reads: the config roots plus each slot name bound to ONE folder.

    An older edition expands ``${roots.<slot>}`` from ``roots`` alone, so a slot bound once keeps
    resolving there; a name two workspaces bind to different folders is left out (never first-wins).
    """

    mirror = {str(name): str(value) for name, value in config_roots.items()}
    folders: dict[str, set[str]] = {}
    for slots in slot_folders.values():
        for name, value in slots.items():
            folders.setdefault(str(name), set()).add(str(value))
    for name, values in folders.items():
        if name not in mirror and len(values) == 1:
            mirror[name] = next(iter(values))
    return dict(sorted(mirror.items()))


def write_machine_roots(
    roots: Mapping[str, str],
    *,
    workspace_roots: Mapping[str, Mapping[str, str]] | None = None,
    dry_run: bool,
    path: Path | None = None,
) -> dict[str, Any]:
    """THE single write site for the registry. ``dry_run`` never touches disk.

    ``_add_stage42_global_args(mutation=True)`` auto-registers ``--dry-run`` for
    every mutation verb, and a verb that forgets to READ it silently mutates on
    a preview. Honouring it here — at the store chokepoint rather than in the
    CLI handler — makes that failure mode unreachable.
    """

    target = Path(path) if path is not None else machine_roots_registry_paths()[0]
    config = {str(name): str(value) for name, value in sorted(roots.items())}
    # ``None`` keeps what the file has, in the file's own schema: a schema-1 file stays legacy and a
    # schema-2 file keeps its mirrored shape, so the next slot read still upgrades it (and drops its
    # slot mirrors, which only that read can tell from config roots). A passed map writes schema 3.
    held = _held_registry(target) if workspace_roots is None else None
    if workspace_roots is not None:
        scoped, schema = workspace_roots, MACHINE_ROOTS_SCHEMA_VERSION
    elif held is not None and held.scoped:
        scoped, schema = held.workspace_roots, held.schema
    else:
        scoped, schema = None, MACHINE_ROOTS_LEGACY_SCHEMA_VERSION
    payload: dict[str, Any] = {"schema_version": schema, "roots": config}
    if scoped is not None:
        payload["workspace_roots"] = _sorted_workspace_roots(scoped)
    if schema >= MACHINE_ROOTS_SCHEMA_VERSION:
        payload["config_roots"] = config
        payload["slot_folders"] = payload["workspace_roots"]
        payload["roots"] = legacy_roots_mirror(config, payload["slot_folders"])
    after = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    try:
        before = target.read_text(encoding="utf-8") if target.is_file() else ""
    except OSError:
        before = ""
    changed = after != before
    result: dict[str, Any] = {
        "path": str(target),
        "dry_run": bool(dry_run),
        "changed": changed,
        "roots": config,
    }
    if dry_run or not changed:
        result["written"] = False
        return result
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(after, encoding="utf-8")
    os.replace(tmp, target)
    machine_roots_cache_clear()
    result["written"] = True
    return result


# ── Expansion (the single chokepoint) ───────────────────────────────────────


def contains_path_tokens(value: Any) -> bool:
    """True when ``value`` (str/dict/list) carries any token this module owns."""

    if isinstance(value, str):
        return EXE_SUFFIX_TOKEN in value or bool(ROOT_TOKEN_RE.search(value))
    if isinstance(value, Mapping):
        return any(contains_path_tokens(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_path_tokens(item) for item in value)
    return False


def expand_config_paths(
    value: Any,
    *,
    field: str = "",
    roots: MachineRoots | None = None,
    check_target_exists: bool = True,
    workspace_id: str = "",
) -> Any:
    """Expand path tokens, raising :class:`MachineRootError` on any problem.

    Use this where a dead path must never reach a caller (spawning a process,
    handing a workdir to a subagent). Use :func:`path_token_issues` where the
    caller must report rather than raise (readiness). ``workspace_id`` names the
    workspace the config belongs to: its slot folder answers ``${roots.<slot>}``
    before any config root does.
    """

    issues: list[PathTokenIssue] = []
    expanded = _walk(
        value,
        field=field,
        roots=roots if roots is not None else load_machine_roots(),
        issues=issues,
        check_target_exists=check_target_exists,
        workspace_id=workspace_id,
    )
    if issues:
        raise MachineRootError(issues)
    return expanded


def path_token_issues(
    value: Any,
    *,
    field: str = "",
    roots: MachineRoots | None = None,
    check_target_exists: bool = True,
    workspace_id: str = "",
) -> list[PathTokenIssue]:
    """Every typed reason ``value``'s path tokens cannot resolve. Never raises."""

    issues: list[PathTokenIssue] = []
    _walk(
        value,
        field=field,
        roots=roots if roots is not None else load_machine_roots(),
        issues=issues,
        check_target_exists=check_target_exists,
        workspace_id=workspace_id,
    )
    return issues


def _walk(
    value: Any,
    *,
    field: str,
    roots: MachineRoots,
    issues: list[PathTokenIssue],
    check_target_exists: bool,
    workspace_id: str = "",
) -> Any:
    if isinstance(value, str):
        return _expand_text(
            value, field=field, roots=roots, issues=issues, check_target_exists=check_target_exists,
            workspace_id=workspace_id,
        )
    if isinstance(value, Mapping):
        return {
            key: _walk(
                item,
                field=f"{field}.{key}" if field else str(key),
                roots=roots,
                issues=issues,
                check_target_exists=check_target_exists,
                workspace_id=workspace_id,
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _walk(
                item,
                field=f"{field}[{index}]" if field else f"[{index}]",
                roots=roots,
                issues=issues,
                check_target_exists=check_target_exists,
                workspace_id=workspace_id,
            )
            for index, item in enumerate(value)
        ]
    return value


def _expand_text(
    text: str,
    *,
    field: str,
    roots: MachineRoots,
    issues: list[PathTokenIssue],
    check_target_exists: bool,
    workspace_id: str = "",
) -> str:
    if "${" not in text:
        return text
    # ``${exe_suffix}`` first: it is a bare suffix with no separators, so once
    # substituted it is just the tail's last path component.
    text = text.replace(EXE_SUFFIX_TOKEN, exe_suffix())
    if not ROOT_TOKEN_RE.search(text):
        return text

    out: list[str] = []
    cursor = 0
    for match in ROOT_TOKEN_RE.finditer(text):
        out.append(text[cursor:match.start()])
        tail_end = _tail_end(text, match.end())
        tail = text[match.end():tail_end]
        resolved = _resolve_root(
            match.group(1).strip(),
            field=field,
            roots=roots,
            issues=issues,
            check_target_exists=check_target_exists,
            workspace_id=workspace_id,
        )
        if resolved is None:
            # Unresolved: keep the literal token + tail. Callers that must not
            # see a dead path use the raising form (or drop the entry); the
            # typed issue is already recorded either way.
            out.append(text[match.start():tail_end])
        else:
            out.append(_join_tail(resolved, tail))
        cursor = tail_end
    out.append(text[cursor:])
    return "".join(out)


def _tail_end(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index] not in _TAIL_TERMINATORS:
        index += 1
    return index


def _join_tail(root: Path, tail: str) -> str:
    """Join ``tail`` onto ``root`` with native separators.

    The tail is split on BOTH separator styles so a config authored on Windows
    (``\\tool\\build``) and one authored on macOS (``/tool/build``) resolve
    identically, and re-joined through ``Path.joinpath`` so the emitted string
    uses whatever separator this OS actually wants. Nothing here concatenates a
    hardcoded separator.
    """

    segments = [segment for segment in re.split(r"[\\/]+", tail) if segment]
    return str(root.joinpath(*segments)) if segments else str(root)


def _resolve_root(
    name: str,
    *,
    field: str,
    roots: MachineRoots,
    issues: list[PathTokenIssue],
    check_target_exists: bool,
    workspace_id: str = "",
) -> Path | None:
    where = f" (field {field})" if field else ""
    if not _ROOT_NAME_RE.match(name):
        issues.append(
            PathTokenIssue(
                code=ISSUE_INVALID_ROOT_TOKEN,
                root_name=name,
                field=field,
                summary=f"Malformed machine-root token '${{roots.{name}}}'{where}",
                fix_hint="Root names must be [A-Za-z0-9_]+ — e.g. ${roots.eternia_launcher}.",
            )
        )
        return None
    # A slot folder IS a config root, in its workspace (plan machine-roots-two-halves §2.2): the
    # reading config's own workspace first, then ``config_roots``, then a slot bound to ONE folder.
    in_workspace = roots.workspace_root(workspace_id, name) if workspace_id else None
    bound = str(in_workspace) if in_workspace is not None else roots.roots.get(name)
    if not bound:
        bindings = roots.slot_folder_bindings(name)
        folders = set(bindings.values())
        if len(folders) > 1:
            named = ", ".join(f"{ws}={bindings[ws]}" for ws in sorted(bindings))
            issues.append(
                PathTokenIssue(
                    code=ISSUE_ROOT_AMBIGUOUS,
                    root_name=name,
                    field=field,
                    summary=f"Machine root '{name}' is only a slot folder, and workspaces bind it to different "
                            f"folders{where}: {named}",
                    fix_hint=f"hermes harness roots set {name} <absolute-local-path> --yes",
                )
            )
            return None
        bound = next(iter(folders)) if folders else ""
    if not bound:
        known = ", ".join(roots.names()) or "(none bound on this machine)"
        issues.append(
            PathTokenIssue(
                code=ISSUE_UNBOUND_ROOT,
                root_name=name,
                field=field,
                summary=f"Machine root '{name}' is not bound on this machine{where}. Bound roots: {known}",
                fix_hint=f"hermes harness roots set {name} <absolute-local-path> --yes",
            )
        )
        return None
    path = Path(bound)
    if check_target_exists and not path.exists():
        issues.append(
            PathTokenIssue(
                code=ISSUE_ROOT_TARGET_MISSING,
                root_name=name,
                field=field,
                summary=f"Machine root '{name}' is bound to a path that does not exist: {bound}{where}",
                fix_hint=f"hermes harness roots set {name} <absolute-local-path> --yes",
            )
        )
        return None
    return path


# ── MCP server resolution ───────────────────────────────────────────────────


def resolve_mcp_servers(
    servers: Mapping[str, Any],
    *,
    roots: MachineRoots | None = None,
    on_issue: Callable[[str, PathTokenIssue], None] | None = None,
    check_target_exists: bool = True,
) -> dict[str, Any]:
    """Expand path tokens and apply the platform gate over an ``mcp_servers`` map.

    A server whose declared ``platforms`` excludes this OS, or whose path tokens
    cannot resolve, is DROPPED rather than handed to a spawn with a dead path —
    "the capability is unavailable" is the honest answer, and readiness/preflight
    carry the typed reason. Servers with no tokens pass through byte-identical.
    """

    resolved_roots = roots if roots is not None else load_machine_roots()
    report = on_issue if on_issue is not None else _log_issue
    out: dict[str, Any] = {}
    for name, cfg in servers.items():
        if not isinstance(cfg, Mapping):
            out[name] = cfg
            continue
        entry = {key: value for key, value in cfg.items() if key != "platforms"}
        if not platform_supported(cfg.get("platforms")):
            report(
                str(name),
                PathTokenIssue(
                    code=ISSUE_PLATFORM_UNSUPPORTED,
                    field=f"mcp_servers.{name}",
                    summary=(
                        f"MCP server '{name}' declares platforms "
                        f"{normalize_platforms(cfg.get('platforms'))}; this machine is "
                        f"{current_platform_key()}"
                    ),
                    fix_hint=f"Provide a {current_platform_key()} binding for '{name}', or use a different capability.",
                ),
            )
            continue
        issues: list[PathTokenIssue] = []
        expanded = _walk(
            entry,
            field=f"mcp_servers.{name}",
            roots=resolved_roots,
            issues=issues,
            check_target_exists=check_target_exists,
        )
        if issues:
            for issue in issues:
                report(str(name), issue)
            continue
        out[name] = expanded
    return out


def _log_issue(name: str, issue: PathTokenIssue) -> None:
    logger.error(
        "MCP server '%s' is unavailable (%s): %s | fix: %s",
        name,
        issue.code,
        issue.summary,
        issue.fix_hint,
    )
