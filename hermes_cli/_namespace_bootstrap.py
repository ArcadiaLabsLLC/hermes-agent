"""Fork-owned, stdlib + ``hermes_constants``: ``HERMES_NAMESPACE`` -> a namespace root, resolved early.

Plan: ``EterniaLauncher/docs/embedded_hermes/planned/ONE_HERMES_INSTALL_PROFILE_NAMESPACE_2026-10-19.md``
§2.1-2.2, §2.8, §4 H1/H1c, §6 Q9 (rows ``RT-NAMESPACE-ROOT``, ``-ID-CHARSET``, ``-PATH-BUDGET``,
``-EXTERNAL-ACCESS``). One code install per machine; N data namespaces inside it. A namespace is a
complete Hermes data root (profiles, agent-runtime, shared DBs, auth, pairing, serve lock) at
``<HERMES_NAMESPACES_DIR or <base parent>/hermes-namespaces>/<id>`` — a SIBLING of the base root,
never inside it — that borrows the base install read-only.

It lives here, beside ``_profile_bootstrap``, and not under ``agent_runtime``: ``main.py`` runs it
before the app's modules import (they cache ``HERMES_HOME`` at import), and importing
``agent_runtime`` costs ~0.4 s of models. Its one non-stdlib import is ``hermes_constants``' root
authority, which ``_apply_profile_override`` already imports at the same moment. ``agent_runtime.namespace`` holds the runtime half
(the store-root isolation assertion, the admin verbs) and imports this module.

The rules, each pinned by ``tests/hermes_cli/test_namespace_bootstrap.py``:

* An id is ``[a-z0-9][a-z0-9-]{0,47}`` (``acct-<16 hex>`` is the per-account form), never a
  Windows device name. A malformed id REFUSES (exit 2): there is no fallback to the base root.
* ``base`` is reserved: it names the base root explicitly (and beats the active record).
* An explicit ``HERMES_HOME`` / ``HERMES_HEAD_HOME`` / ``HERMES_AGENT_RUNTIME_ROOT`` must lie
  inside the namespace or resolution refuses. The one exception is a ``HERMES_HOME`` that IS
  the base root (an installer-persisted home): it names the install, and is replaced.
* Outside the launcher (``HERMES_LAUNCHER_SPAWNED`` != ``1``) only the namespace named by
  ``<base>/namespace-active.json`` is reachable (owner ruling Q9, 2026-10-19): no record and a
  named namespace -> ``namespace_external_disabled``; another id -> ``namespace_not_active``;
  no namespace named and a record -> the record's namespace. With no namespace named and no
  record the process keeps the base root exactly as before; install verbs (``pm``, ``update``)
  never follow the record; ``hermes namespace …`` resolves its targets explicitly.
* Fences: ``HERMES_DEPENDENCY_ROOT=<base>``, ``HERMES_REGISTRY_WRITE_FENCE=1`` and
  ``HERMES_DISABLE_LAZY_INSTALLS=1`` are ``setdefault``ed, so a namespace never syncs its own venv
  nor writes the user's registry.
* Path budget (Windows ``MAX_PATH``): a root longer than :data:`ROOT_BUDGET` refuses unless the
  OS has long paths enabled.

Unset ``HERMES_NAMESPACE`` in a launcher-spawned process touches nothing: no env write, no file read.

"base" names three different things (row ``RT-THREE-BASES``, naming map
``docs/agent-runtime-harness/planned/naming-and-address-map-2026-10-25.md``); code, logs and docs qualify which:

* ``base-root`` — the install's own data root (:data:`BASE_ID`, :func:`base_root`; ``namespace:base`` in an
  address). It holds an install — code, environments, ``namespace-active.json`` — and, after a seed, only
  superseded copies (``SEEDED_INTO.json``). It is NOT a namespace.
* ``agent-profile:base`` — the ``profiles/base`` agent profile (:data:`BASE_PROFILE`, ``Layout.head_home``):
  the launcher's serve runs under it (``HERMES_HEAD_HOME``), and today it holds EVERY persona instance's chat
  ``state.db``. Why: the 2026-07-27 split read — CLI turns minted transcripts into their own profile's
  ``state.db`` while the cockpit read ``profiles/base``, so one head was pinned for every chat
  (``agent_runtime/chat_session_scope.py``). Ruling 4 moves each chat head to its own agent profile
  (``RT-CHAT-HEAD-PER-PROFILE``).
* ``persona-instance:base`` — the ``personainst_base`` persona instance, the only seeded agent: an agent
  you chat with, which happens to run on ``agent-profile:base``.
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
LAUNCHER_ENV = "HERMES_LAUNCHER_SPAWNED"
#: How THIS process reached its namespace (``env`` | ``argv`` | ``active-file``) — exported for children.
SOURCE_ENV = "HERMES_NAMESPACE_SOURCE"
#: What KIND of namespace it is, which only the launcher knows (RT-NAMESPACE-ORIGIN, naming map ruling 2):
#: ``account`` (the signed-in account's) or ``launcher-profile`` (an ``ETERNIA_PROFILE`` sandbox / QA store).
ORIGIN_ENV = "HERMES_NAMESPACE_ORIGIN"
ORIGIN_ACCOUNT, ORIGIN_LAUNCHER_PROFILE = "account", "launcher-profile"
ORIGINS = (ORIGIN_ACCOUNT, ORIGIN_LAUNCHER_PROFILE)
DEPENDENCY_ENV = "HERMES_DEPENDENCY_ROOT"
FLAG = "--namespace"
#: ``base-root``: the reserved id naming the install's own data root — never a namespace.
BASE_ID = "base"
DIRNAME = "hermes-namespaces"
MANIFEST_NAME = "namespace.json"
ACTIVE_RECORD_NAME = "namespace-active.json"
SCHEMA = 1
#: ``namespace-active.json`` schemas read: 1 ``{schema, namespace}``; 2 adds ``namespaces_dir`` (the shared
#: folder the launcher hands both editions — RT-NAMESPACE-ACTIVE-RECORD-DIR).
ACTIVE_RECORD_SCHEMAS = (1, 2)
#: ``agent-profile:base``: the head profile every namespace's serve runs under (not the base-root).
BASE_PROFILE = "base"
STORE_DIRNAME = "agent-runtime"
#: Explicit paths a namespaced process may carry only when they lie inside the namespace.
PINNED_PATH_ENVS = ("HERMES_HOME", "HERMES_HEAD_HOME", "HERMES_AGENT_RUNTIME_ROOT")
#: ``setdefault`` in every namespaced process (the base key is added at resolution).
FENCE_DEFAULTS = {"HERMES_REGISTRY_WRITE_FENCE": "1", "HERMES_DISABLE_LAZY_INSTALLS": "1"}
#: Verbs that act on the INSTALL, never on data: no active-record redirect.
INSTALL_VERBS = frozenset({"pm", "update"})
#: ``hermes namespace …`` resolves its targets explicitly, never through this process's namespace.
ADMIN_VERB = "namespace"

_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
ACCOUNT_ID = re.compile(r"acct-[0-9a-f]{16}")
#: The opt-in Developer Edition sandbox of an account (launcher plan EDITION_SWITCH §2.1, row
#: RT-NAMESPACE-SANDBOX-KIND): ``acct-<16 hex>-dev``, seeded at most once from ``acct-<the same hex>``.
ACCOUNT_SANDBOX_ID = re.compile(r"(acct-[0-9a-f]{16})-dev")
KIND_ACCOUNT, KIND_ACCOUNT_SANDBOX, KIND_PROFILE = "account", "account-sandbox", "profile"


def namespace_kind(ns_id: str) -> str:
    """``account`` (``acct-<16 hex>``) | ``account-sandbox`` (``acct-<16 hex>-dev``) | ``profile``."""
    if ACCOUNT_ID.fullmatch(ns_id):
        return KIND_ACCOUNT
    return KIND_ACCOUNT_SANDBOX if ACCOUNT_SANDBOX_ID.fullmatch(ns_id) else KIND_PROFILE


def inferred_origin(ns_id: str) -> str:
    """The origin an id's FORM implies, for a manifest written before the launcher handed one in."""
    return ORIGIN_LAUNCHER_PROFILE if namespace_kind(ns_id) == KIND_PROFILE else ORIGIN_ACCOUNT


def namespace_origin(manifest: Mapping[str, object] | None, ns_id: str) -> str:
    """The namespace's recorded ``origin``; the id-form inference only when none is recorded."""
    recorded = manifest.get("origin") if isinstance(manifest, Mapping) else None
    return recorded if recorded in ORIGINS else inferred_origin(ns_id)


def sandbox_account(ns_id: str) -> str | None:
    """The account namespace a sandbox belongs to (its one sanctioned seed source), else ``None``."""
    match = ACCOUNT_SANDBOX_ID.fullmatch(ns_id)
    return match.group(1) if match else None
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
    EXTERNAL_DISABLED = "namespace_external_disabled"
    NOT_ACTIVE = "namespace_not_active"
    ACTIVE_RECORD_INVALID = "namespace_active_record_invalid"
    RESERVED = "namespace_reserved"
    NOT_FOUND = "namespace_not_found"
    BUSY = "namespace_busy"
    IN_USE_BY_THIS_PROCESS = "namespace_in_use_by_this_process"
    ALREADY_SEEDED = "namespace_already_seeded"
    NOT_FRESH = "namespace_not_fresh"
    SEED_SOURCE = "namespace_seed_source"
    MEMORIES_NOT_ACCOUNT = "namespace_memories_not_account"
    INSTANCE_NOT_REBASED = "namespace_instance_not_rebased"
    DEV_ONLY = "namespace_dev_only"
    INVALID_ORIGIN = "namespace_invalid_origin"
    EPOCH_NEWER = "namespace_epoch_newer"
    EPOCH_CONSENT_REQUIRED = "namespace_epoch_consent_required"


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
    # The one root authority (``_apply_profile_override`` imports it for ``active_profile`` too):
    # <root>/profiles/<p> -> <root>, a home under the platform home -> the platform home.
    from hermes_constants import get_default_hermes_root

    return Path(get_default_hermes_root(home=str(env.get("HERMES_HOME") or "").strip()))


def namespaces_dir(env: Mapping[str, str], base: Path) -> Path:
    """``HERMES_NAMESPACES_DIR``; else, outside the launcher, the active record's ``namespaces_dir``
    (schema 2); else ``<base parent>/hermes-namespaces``."""
    override = str(env.get(DIR_ENV) or "").strip()
    recorded = None if override or launcher_spawned(env) else _active_record_dir(base)
    folder = Path(override).expanduser() if override else (recorded or base.parent / DIRNAME)
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


def read_active_record(base: Path) -> str | None:
    """The id ``<base>/namespace-active.json`` names, ``None`` when there is no record; malformed refuses."""
    record = _active_record(base)
    return None if record is None else record["namespace"]


def _active_record_dir(base: Path) -> Path | None:
    """The schema-2 record's ``namespaces_dir``; ``None`` for no record or a schema-1 one."""
    record = _active_record(base)
    return None if record is None or record.get("namespaces_dir") is None else Path(record["namespaces_dir"])


def _active_record(base: Path) -> dict[str, str] | None:
    """``{namespace[, namespaces_dir]}`` from ``<base>/namespace-active.json``; malformed refuses."""
    path = base / ACTIVE_RECORD_NAME
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise NamespaceRefused(Reason.ACTIVE_RECORD_INVALID, f"{path}: {exc}") from exc
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NamespaceRefused(Reason.ACTIVE_RECORD_INVALID, f"{path}: not JSON") from exc
    schema = record.get("schema") if isinstance(record, dict) else None
    folder = record.get("namespaces_dir") if isinstance(record, dict) else None
    if (schema not in ACTIVE_RECORD_SCHEMAS or isinstance(schema, bool) or not isinstance(record.get("namespace"), str)
            or (schema == 2 and not (isinstance(folder, str) and Path(folder).is_absolute()))):
        raise NamespaceRefused(
            Reason.ACTIVE_RECORD_INVALID,
            f"{path}: want {{\"schema\": 1, \"namespace\": <id>}} or "
            f"{{\"schema\": 2, \"namespace\": <id>, \"namespaces_dir\": <absolute dir>}}")
    try:
        ns_id = validate_id(record["namespace"])
    except NamespaceRefused as exc:
        raise NamespaceRefused(Reason.ACTIVE_RECORD_INVALID, f"{path}: {exc.detail}") from exc
    if ns_id == BASE_ID:
        raise NamespaceRefused(Reason.ACTIVE_RECORD_INVALID, f"{path}: the active record cannot name 'base' (the base-root, not a namespace)")
    return {"namespace": ns_id, **({"namespaces_dir": folder} if schema == 2 else {})}


def launcher_spawned(env: Mapping[str, str]) -> bool:
    return str(env.get(LAUNCHER_ENV) or "") == "1"


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
    except Exception:  # a broken parser import must not decide a namespace
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
    #: ``env`` | ``argv`` | ``active-file`` | ``none`` | ``admin``
    source: str
    argv: list[str]
    #: ``""`` for the base root.
    namespace: str


def resolve_cli(argv: Sequence[str], env: Mapping[str, str]) -> CliResolution:
    """Pure: what this CLI process's namespace is, or a typed refusal. Reads at most the active record."""
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
    external = not launcher_spawned(env)
    if requested is None:
        if not external or verb in INSTALL_VERBS:
            return CliResolution(None, "none", rest, "")
        requested, source = read_active_record(base_root(env)), "active-file"
        if requested is None:
            return CliResolution(None, "none", rest, "")
    elif external:
        active = read_active_record(base_root(env))
        if active is None:
            raise NamespaceRefused(
                Reason.EXTERNAL_DISABLED,
                f"outside the launcher only the signed-in account's namespace is reachable, and only while "
                f"'Allow agent use outside the launcher' is on; there is no {ACTIVE_RECORD_NAME}")
        if active != requested:
            raise NamespaceRefused(
                Reason.NOT_ACTIVE, f"outside the launcher only the active namespace is reachable; asked for {requested!r}")
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
    # The dir a record named (RT-NAMESPACE-ACTIVE-RECORD-DIR) is exported, so every child agrees on it.
    for key, value in {DEPENDENCY_ENV: str(item.base_root), DIR_ENV: str(item.namespaces_dir), **FENCE_DEFAULTS}.items():
        if key not in env:
            out[key] = value
    return out


_STORE_EPOCH_ALIAS = "_hermes_store_epoch"


def store_epoch_module():
    """``agent_runtime.store_epoch`` without importing the ``agent_runtime`` package (RT-STORE-EPOCH).

    The package ``__init__`` imports the models (~0.4 s); this module and ``probe`` run before any of
    that. The epoch module is stdlib-only by contract, so loading its file under a private name is
    the same code; when the package has already imported it, that one object is used.
    """
    loaded = sys.modules.get("agent_runtime.store_epoch") or sys.modules.get(_STORE_EPOCH_ALIAS)
    if loaded is not None:
        return loaded
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "agent_runtime" / "store_epoch.py"
    spec = importlib.util.spec_from_file_location(_STORE_EPOCH_ALIAS, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_STORE_EPOCH_ALIAS] = module
    spec.loader.exec_module(module)
    return module


def requested_origin(env: Mapping[str, str]) -> str | None:
    """``HERMES_NAMESPACE_ORIGIN`` as handed in, ``None`` when unset; any other word refuses."""
    raw = str(env.get(ORIGIN_ENV) or "").strip()
    if not raw:
        return None
    if raw not in ORIGINS:
        raise NamespaceRefused(Reason.INVALID_ORIGIN, f"{ORIGIN_ENV}={raw!r}; want one of {', '.join(ORIGINS)}")
    return raw


def ensure_manifest(item: Layout, origin: str | None = None) -> bool:
    """Write ``namespace.json`` on first resolve; True when this call created it.

    A new store is stamped at creation with this build's epoch (RT-STORE-EPOCH): it was shaped by
    this build, so no consent is ever asked for it. It records ``origin`` (RT-NAMESPACE-ORIGIN): the
    one the launcher handed in, else the id form's. A manifest written before ``origin`` existed gets
    it once, the same way; a recorded origin is never rewritten.
    """
    if item.manifest_path.is_file():
        _backfill_origin(item, origin)
        return False
    item.root.mkdir(parents=True, exist_ok=True)
    epoch = store_epoch_module()
    record = {"schema": SCHEMA, "id": item.id, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "epoch": epoch.epoch_block(), "origin": origin or inferred_origin(item.id)}
    try:
        with open(item.manifest_path, "x", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, sort_keys=True)
    except FileExistsError:
        return False
    return True


def _backfill_origin(item: Layout, origin: str | None) -> None:
    try:
        record = json.loads(item.manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return  # an unreadable manifest is the epoch guard's to judge, never rewritten here
    if not isinstance(record, dict) or record.get("origin") in ORIGINS:
        return
    record["origin"] = origin or inferred_origin(item.id)
    tmp = item.manifest_path.with_suffix(".json.origin.tmp")
    try:
        tmp.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, item.manifest_path)
    except OSError:
        tmp.unlink(missing_ok=True)


def apply_cli_namespace(argv: list[str] | None = None, environ: MutableMapping[str, str] | None = None) -> CliResolution:
    """``main._apply_profile_override``'s first act: resolve, strip the flag, export the env, fence.

    A refusal prints one JSON line on stderr and exits 2 — the process never starts on a guess.
    """
    target = os.environ if environ is None else environ
    args = sys.argv if argv is None else argv
    try:
        res = resolve_cli(args, target)
        if res.layout is not None:
            ensure_manifest(res.layout, requested_origin(target))
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
        "max_path": MAX_PATH_CHARS, "long_paths": long_paths_enabled(), "launcher_spawned": launcher_spawned(env),
        "namespace": None, "root": None, "root_length": None, "active": None, "refusal": None, "epoch": None,
    }
    try:
        base = base_root(env)
        out["base_root"], out["namespaces_dir"] = str(base), str(namespaces_dir(env, base))
        out["active"] = read_active_record(base)
        requested = ns_id if ns_id is not None else (str(env.get(ENV) or "") or None)
        if requested is not None:
            out["namespace"] = validate_id(requested)
            if requested != BASE_ID:
                item = layout(requested, env, long_paths=True)
                out["root"], out["root_length"] = str(item.root), item.root_length
                layout(requested, env)  # the budget refusal, reported beside the length it measured
                decision = store_epoch_module().guard(item.manifest_path, env, write=False)
                out["epoch"] = decision.payload()
                if decision.verdict == "newer":  # consent_required rides `epoch.verdict`: the launcher asks
                    raise NamespaceRefused(
                        Reason.EPOCH_NEWER,
                        f"{item.id!r} is at store epoch {decision.stored}; this build reads epoch {decision.mine}")
    except NamespaceRefused as exc:
        out["refusal"] = {"reason": exc.reason.value, "detail": exc.detail}
    return out
