"""Fork-owned, stdlib only: ``HERMES_NAMESPACE`` -> a namespace root, resolved before any hermes module imports.

Plan: ``EterniaLauncher/docs/embedded_hermes/planned/ONE_HERMES_INSTALL_PROFILE_NAMESPACE_2026-10-19.md``
§2.1-2.2, §2.8, §4 H1/H1c (rows ``RT-NAMESPACE-ROOT``, ``-ID-CHARSET``, ``-PATH-BUDGET``). One code install per machine; N data namespaces inside it. A namespace is a
complete Hermes data root (profiles, agent-runtime, shared DBs, auth, pairing, serve lock) at
``<HERMES_NAMESPACES_DIR or <base parent>/hermes-namespaces>/<id>`` — a SIBLING of the base root,
never inside it — that borrows the base install read-only.

It lives here, beside ``_profile_bootstrap``, and not under ``agent_runtime``: ``main.py`` runs it
before any hermes module is importable (modules cache ``HERMES_HOME`` at import), and importing
``agent_runtime`` costs ~0.4 s of models. ``agent_runtime.namespace`` holds the runtime half
(the store-root isolation assertion, the admin verbs) and imports this module.

The rules, each pinned by ``tests/hermes_cli/test_namespace_bootstrap.py``:

* An id is ``[a-z0-9][a-z0-9-]{0,47}`` (``acct-<16 hex>`` is the per-account form), never a
  Windows device name. A malformed id REFUSES (exit 2): there is no fallback to the base root.
* ``base`` is reserved: it names the base root explicitly (and beats the active record).
* An explicit ``HERMES_HOME`` / ``HERMES_HEAD_HOME`` / ``HERMES_AGENT_RUNTIME_ROOT`` must lie
  inside the namespace or resolution refuses. The one exception is a ``HERMES_HOME`` that IS
  the base root (an installer-persisted home): it names the install, and is replaced.
* Fences: ``HERMES_DEPENDENCY_ROOT=<base>``, ``HERMES_REGISTRY_WRITE_FENCE=1`` and
  ``HERMES_DISABLE_LAZY_INSTALLS=1`` are ``setdefault``ed, so a namespace never syncs its own venv
  nor writes the user's registry.
* Path budget (Windows ``MAX_PATH``): a root longer than :data:`ROOT_BUDGET` refuses unless the
  OS has long paths enabled.

Unset ``HERMES_NAMESPACE`` in a launcher-spawned process touches nothing: no env write, no file read.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

ENV = "HERMES_NAMESPACE"
DIR_ENV = "HERMES_NAMESPACES_DIR"
SOURCE_ENV = "HERMES_NAMESPACE_SOURCE"
DEPENDENCY_ENV = "HERMES_DEPENDENCY_ROOT"
FLAG = "--namespace"
BASE_ID = "base"
DIRNAME = "hermes-namespaces"
MANIFEST_NAME = "namespace.json"
SCHEMA = 1
BASE_PROFILE = "base"
STORE_DIRNAME = "agent-runtime"
#: Explicit paths a namespaced process may carry only when they lie inside the namespace.
PINNED_PATH_ENVS = ("HERMES_HOME", "HERMES_HEAD_HOME", "HERMES_AGENT_RUNTIME_ROOT")
#: ``setdefault`` in every namespaced process (the base key is added at resolution).
FENCE_DEFAULTS = {"HERMES_REGISTRY_WRITE_FENCE": "1", "HERMES_DISABLE_LAZY_INSTALLS": "1"}
#: ``hermes namespace …`` resolves its targets explicitly, never through this process's namespace.
ADMIN_VERB = "namespace"

_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
ACCOUNT_ID = re.compile(r"acct-[0-9a-f]{16}")
_WINDOWS_DEVICE = re.compile(r"con|prn|aux|nul|com[0-9]|lpt[0-9]")

#: Windows ``MAX_PATH`` (260) less the terminating NUL.
MAX_PATH_CHARS = 259
#: Measured 2026-10-19: the longest path ``agent_runtime/paths.py`` builds below a namespace root with
#: 32-character ids (``agent-runtime/realm_sync/<realm>/prefab_conflicts/<profile>/<prefab>.json``).
#: ``tests/agent_runtime/test_namespace_path_budget.py`` re-measures it from the module itself.
LONGEST_STORE_SUFFIX = 146
ROOT_BUDGET = MAX_PATH_CHARS - LONGEST_STORE_SUFFIX


class Reason(StrEnum):
    INVALID_ID = "namespace_invalid_id"
    ARGV_ENV_MISMATCH = "namespace_argv_env_mismatch"
    BASE_UNKNOWN = "namespace_base_unknown"
    CONTAINMENT = "namespace_containment"
    HOME_ESCAPE = "namespace_home_escape"
    ISOLATION = "namespace_isolation"
    ROOT_TOO_LONG = "namespace_root_too_long"
    RESERVED = "namespace_reserved"
    NOT_FOUND = "namespace_not_found"
    BUSY = "namespace_busy"
    IN_USE_BY_THIS_PROCESS = "namespace_in_use_by_this_process"
    ALREADY_SEEDED = "namespace_already_seeded"
    NOT_FRESH = "namespace_not_fresh"
    SEED_SOURCE = "namespace_seed_source"


class NamespaceRefused(RuntimeError):
    """A typed refusal: the process does not start, the verb does not run."""

    def __init__(self, reason: Reason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail

    def payload(self) -> dict[str, object]:
        return {"ok": False, "error": "namespace_refused", "reason": self.reason.value, "detail": self.detail}


def validate_id(raw: object) -> str:
    """The id itself, or :class:`NamespaceRefused` — never a normalised or fallback value."""
    text = str(raw)
    if not _ID.fullmatch(text) or _WINDOWS_DEVICE.fullmatch(text):
        raise NamespaceRefused(
            Reason.INVALID_ID,
            f"{text!r} is not a namespace id: [a-z0-9][a-z0-9-]{{0,47}}, no separators, no '..', "
            "no Windows device name; nothing falls back to the base root",
        )
    return text


def namespace_stamp(env: Mapping[str, str] | None = None) -> str:
    """The id a record carries: ``""`` for the base root (unset or ``base``). Never raises; never the subject."""
    raw = str((os.environ if env is None else env).get(ENV) or "")
    return "" if raw in ("", BASE_ID) else raw


def platform_default_home(env: Mapping[str, str]) -> Path:
    if sys.platform == "win32":
        local = str(env.get("LOCALAPPDATA") or "").strip()
        return (Path(local).expanduser() if local else Path.home() / "AppData" / "Local") / "hermes"
    return Path.home() / ".hermes"


def _norm(path: Path | str) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def is_inside(path: Path | str, root: Path | str) -> bool:
    """``path`` is ``root`` or below it (symlinks and case folded the platform's way)."""
    p, r = _norm(path), _norm(root)
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def base_root(env: Mapping[str, str]) -> Path:
    """The install's base root: ``HERMES_DEPENDENCY_ROOT``, else ``HERMES_HOME``'s root, else the platform home."""
    lender = str(env.get(DEPENDENCY_ENV) or "").strip()
    if lender:
        path = Path(lender).expanduser()
        if not path.is_absolute():
            raise NamespaceRefused(Reason.BASE_UNKNOWN, f"{DEPENDENCY_ENV} must be absolute, got {lender!r}")
        return path
    native = platform_default_home(env)
    home = str(env.get("HERMES_HOME") or "").strip()
    if not home:
        return native
    path = Path(home).expanduser()
    if is_inside(path, native):
        return native
    return path.parent.parent if path.parent.name == "profiles" else path


def namespaces_dir(env: Mapping[str, str], base: Path) -> Path:
    override = str(env.get(DIR_ENV) or "").strip()
    folder = Path(override).expanduser() if override else base.parent / DIRNAME
    if not folder.is_absolute():
        raise NamespaceRefused(Reason.CONTAINMENT, f"{DIR_ENV} must be absolute, got {override!r}")
    if is_inside(folder, base) or is_inside(base, folder):
        raise NamespaceRefused(
            Reason.CONTAINMENT, f"the namespaces dir {folder} and the base root {base} may not contain each other")
    return folder


_LONG_PATHS: list[bool] = []


def long_paths_enabled() -> bool:
    """True off Windows; on Windows, ``LongPathsEnabled`` = 1 (a registry READ — the fence allows reads)."""
    if sys.platform != "win32":
        return True
    if not _LONG_PATHS:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
                _LONG_PATHS.append(int(winreg.QueryValueEx(key, "LongPathsEnabled")[0]) == 1)
        except (OSError, ValueError):
            _LONG_PATHS.append(False)
    return _LONG_PATHS[0]


@dataclass(frozen=True, slots=True)
class Layout:
    """One namespace's paths. ``classify`` answers where any path lies relative to it."""

    id: str
    base_root: Path
    namespaces_dir: Path
    root: Path

    @property
    def store_root(self) -> Path:
        return self.root / STORE_DIRNAME

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def head_home(self) -> Path:
        return self.home(BASE_PROFILE)

    @property
    def root_length(self) -> int:
        return len(str(self.root))

    def home(self, profile: str = BASE_PROFILE) -> Path:
        return self.root / "profiles" / profile

    def classify(self, path: Path | str) -> str:
        """``own`` | ``base`` | ``namespace:<id>`` | ``outside`` — only ``own`` is ever admitted."""
        if is_inside(path, self.root):
            return "own"
        if is_inside(path, self.namespaces_dir):
            rel = os.path.relpath(_norm(path), _norm(self.namespaces_dir))
            return f"namespace:{rel.split(os.sep)[0]}"
        if is_inside(path, self.base_root):
            return "base"
        return "outside"


def layout(ns_id: str, env: Mapping[str, str], *, long_paths: bool | None = None) -> Layout:
    """The layout of namespace *ns_id* (never ``base``), or a typed refusal."""
    ns_id = validate_id(ns_id)
    if ns_id == BASE_ID:
        raise NamespaceRefused(Reason.RESERVED, "'base' names the base root, not a namespace")
    base = base_root(env)
    folder = namespaces_dir(env, base)
    item = Layout(ns_id, base, folder, folder / ns_id)
    allowed = long_paths_enabled() if long_paths is None else long_paths
    if item.root_length > ROOT_BUDGET and not allowed:
        raise NamespaceRefused(
            Reason.ROOT_TOO_LONG,
            f"{item.root} is {item.root_length} characters; the budget is {ROOT_BUDGET} "
            f"({MAX_PATH_CHARS} less the {LONGEST_STORE_SUFFIX}-character longest store path) and this "
            "OS does not have long paths enabled",
        )
    return item


def strip_namespace_flag(argv: Sequence[str]) -> tuple[str | None, list[str]]:
    """``(value, argv without the flag)``; ``--namespace X`` / ``--namespace=X`` anywhere before ``--``."""
    out = [argv[0]] if argv else []
    value: str | None = None
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            out.extend(argv[i:])
            break
        found = None
        if arg == FLAG:
            if i + 1 >= len(argv):
                raise NamespaceRefused(Reason.INVALID_ID, f"{FLAG} needs an id")
            found, i = argv[i + 1], i + 2
        elif arg.startswith(FLAG + "="):
            found, i = arg.split("=", 1)[1], i + 1
        else:
            out.append(arg)
            i += 1
            continue
        if value is not None and found != value:
            raise NamespaceRefused(Reason.ARGV_ENV_MISMATCH, f"{FLAG} given twice: {value!r} and {found!r}")
        value = found
    return value, out


def first_verb(argv: Sequence[str]) -> str | None:
    """The first subcommand token (top-level value flags skipped, read off the real parser)."""
    try:
        from hermes_cli._parser import top_level_value_flag_sets

        required, optional = top_level_value_flag_sets()
    except Exception:  # noqa: BLE001 — a broken parser import must not decide a namespace
        required, optional = frozenset({"-p", "--profile"}), frozenset()
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            return None
        if not arg.startswith("-"):
            return arg
        takes = "=" not in arg and i + 1 < len(argv) and (
            arg in required or (arg in optional and not argv[i + 1].startswith("-")))
        i += 2 if takes else 1
    return None


@dataclass(frozen=True, slots=True)
class CliResolution:
    layout: Layout | None
    #: ``env`` | ``argv`` | ``none`` | ``admin``
    source: str
    argv: list[str]
    #: ``""`` for the base root.
    namespace: str


def resolve_cli(argv: Sequence[str], env: Mapping[str, str]) -> CliResolution:
    """Pure: what this CLI process's namespace is, or a typed refusal. Reads no file."""
    flag, rest = strip_namespace_flag(argv)
    verb = first_verb(rest)
    if verb == ADMIN_VERB:
        return CliResolution(None, "admin", rest, "")
    env_value = str(env.get(ENV) or "")
    if flag is not None and env_value and flag != env_value:
        raise NamespaceRefused(Reason.ARGV_ENV_MISMATCH, f"{FLAG} {flag!r} but {ENV}={env_value!r}")
    requested, source = (flag, "argv") if flag is not None else (env_value or None, "env")
    if requested is not None:
        validate_id(requested)
    if requested == BASE_ID:
        return CliResolution(None, source, rest, "")
    if requested is None:
        return CliResolution(None, "none", rest, "")
    item = layout(requested, env)
    for key in PINNED_PATH_ENVS:
        value = str(env.get(key) or "").strip()
        if not value:
            continue
        path = Path(value).expanduser()
        if key == "HERMES_HOME" and _norm(path) == _norm(item.base_root):
            continue  # names the install, not a home: replaced below
        where = item.classify(path)
        if where != "own":
            raise NamespaceRefused(
                Reason.HOME_ESCAPE, f"{key}={value} lies in {where}, not inside namespace {requested!r} ({item.root})")
    return CliResolution(item, source, rest, requested)


def env_updates(res: CliResolution, env: Mapping[str, str]) -> dict[str, str]:
    """The environment a resolved namespace gives this process and every child it spawns."""
    if res.layout is None:
        return {ENV: BASE_ID, SOURCE_ENV: res.source} if res.source in ("env", "argv") else {}
    item = res.layout
    out = {ENV: item.id, SOURCE_ENV: res.source}
    home = str(env.get("HERMES_HOME") or "").strip()
    if not home or _norm(Path(home).expanduser()) == _norm(item.base_root):
        out["HERMES_HOME"] = str(item.home())
    if not str(env.get("HERMES_HEAD_HOME") or "").strip():
        out["HERMES_HEAD_HOME"] = str(item.head_home)
    if not str(env.get("HERMES_AGENT_RUNTIME_ROOT") or "").strip():
        out["HERMES_AGENT_RUNTIME_ROOT"] = str(item.store_root)
    for key, value in {DEPENDENCY_ENV: str(item.base_root), **FENCE_DEFAULTS}.items():
        if key not in env:
            out[key] = value
    return out


def ensure_manifest(item: Layout) -> bool:
    """Write ``namespace.json`` on first resolve; True when this call created it."""
    if item.manifest_path.is_file():
        return False
    item.root.mkdir(parents=True, exist_ok=True)
    record = {"schema": SCHEMA, "id": item.id, "created_at": datetime.now(UTC).isoformat(timespec="seconds")}
    try:
        with open(item.manifest_path, "x", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, sort_keys=True)
    except FileExistsError:
        return False
    return True


def apply_cli_namespace(argv: list[str] | None = None, environ: MutableMapping[str, str] | None = None) -> CliResolution:
    """``main._apply_profile_override``'s first act: resolve, strip the flag, export the env, fence.

    A refusal prints one JSON line on stderr and exits 2 — the process never starts on a guess.
    """
    target = os.environ if environ is None else environ
    args = sys.argv if argv is None else argv
    try:
        res = resolve_cli(args, target)
        if res.layout is not None:
            ensure_manifest(res.layout)
    except NamespaceRefused as exc:
        sys.stderr.write(json.dumps(exc.payload()) + "\n")
        sys.stderr.flush()
        raise SystemExit(2) from exc
    args[:] = res.argv
    target.update(env_updates(res, target))
    if res.layout is not None and environ is None:
        from hermes_cli import _registry_write_fence

        _registry_write_fence.install_if_requested()
    return res


def probe(env: Mapping[str, str], ns_id: str | None = None) -> dict[str, object]:
    """``hermes namespace probe``: the launcher's pre-spawn capability check. Reads only; writes nothing."""
    out: dict[str, object] = {
        "schema": SCHEMA, "namespaces_dir": None, "base_root": None, "root_budget": ROOT_BUDGET,
        "max_path": MAX_PATH_CHARS, "long_paths": long_paths_enabled(),
        "namespace": None, "root": None, "root_length": None, "refusal": None,
    }
    try:
        base = base_root(env)
        out["base_root"], out["namespaces_dir"] = str(base), str(namespaces_dir(env, base))
        requested = ns_id if ns_id is not None else (str(env.get(ENV) or "") or None)
        if requested is not None:
            out["namespace"] = validate_id(requested)
            if requested != BASE_ID:
                item = layout(requested, env, long_paths=True)
                out["root"], out["root_length"] = str(item.root), item.root_length
                layout(requested, env)  # the budget refusal, reported beside the length it measured
    except NamespaceRefused as exc:
        out["refusal"] = {"reason": exc.reason.value, "detail": exc.detail}
    return out
