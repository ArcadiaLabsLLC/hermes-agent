"""OPT-IN (``HERMES_TEST_KEEP_PLUGIN_MODULES=1``): keep bundled plugin MODULES loaded between tests.

OFF by default — the owner has not ruled that plugin modules may outlive a test (fork-hygiene row
"Per-test plugin LOAD is what is left of plugin rediscovery"). With it on, a bundled directory plugin's
package is executed once per process; every later load hands the kept module back and upstream runs
``register()`` against the fresh, reset managers exactly as before. Registries are untouched by this
module: only the import is skipped.

A kept module is re-used only when nothing a cold import would have seen differently has changed.
Otherwise the load is cold (a real import), and the cold result is what is kept next. The checks, each
a contract test in ``tests/test_plugin_module_keep_downstream.py``:

1. **Rebound globals** — every global of the package and of the submodules its import pulled in is
   restored to the binding the import left (a ``register()`` that rebinds ``_STATE = ...`` is undone).
2. **Mutated module state** — a module-level container, a class defined in the package or a plain
   object created by it whose contents differ (shallow, by identity) from right after the import:
   cold. ``logging.Logger``s, modules, functions and immutable values are not compared (a cold import
   gets the same logger back; the rest cannot change in place).
3. **Patched captures** — every top-level ``from X import a as b`` of the package's own source (parsed
   once): when ``X.a`` is no longer the object the import bound to ``b`` (a test patched ``X.a``, or
   un-patched it), cold.
4. **Environment** — every string constant in the package's code that is set in the environment at
   import time or is spelled like a variable (``UPPER_SNAKE``): when its value differs from the
   import's, cold.
5. **Home capture** — a module whose globals hold the importing test's Hermes home (a ``str``/path
   under it, one container level deep) is never kept.

Not covered (the stated leak risks): state mutated deeper than one level inside a kept object;
import-time reads of files, config or the clock; a ``from X import a`` inside a function or a
conditional block below module level; a background thread or ``atexit`` hook started by the import
(cold runs them per test, kept once).

The opt-out is ``cold_plugin_discovery`` (``plugin_discovery_cache``): its bypass makes every load cold.
"""

from __future__ import annotations

import ast
import os
import re
import sys
import threading
import logging
import types
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any

import pytest

ENV = "HERMES_TEST_KEEP_PLUGIN_MODULES"
_MARK = "_fork_plugin_module_keep"
_LOCK = threading.RLock()
_STATE = {"hits": 0, "misses": 0}
_COLD_REASONS: dict[str, int] = {}
_IMMUTABLE = (str, bytes, int, float, complex, bool, type(None), tuple, frozenset, range, PurePath)
_CONTAINERS = (dict, list, set, bytearray)
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+")


def enabled() -> bool:
    return os.environ.get(ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def stats() -> dict[str, Any]:
    with _LOCK:
        return {**_STATE, "cold_reasons": dict(_COLD_REASONS)}


def clear() -> None:
    with _LOCK:
        _KEPT.clear()


@dataclass
class _Kept:
    name: str
    modules: dict[str, types.ModuleType]
    globals_: dict[str, dict[str, Any]]
    contents: dict[tuple[str, str], Any]
    captures: list[tuple[str, str, str, str]]  # (module, bound name, source module, source attr)
    env: dict[str, str | None]
    stamp: int | None = None
    reasons: list[str] = field(default_factory=list)


_KEPT: dict[tuple[str, str], _Kept] = {}


def _attrs_picture(value: Any) -> Any:
    attrs = getattr(value, "__dict__", None)
    if not (isinstance(value, type) or isinstance(attrs, dict)):
        return None
    items = dict(vars(value)) if isinstance(value, type) else dict(attrs)
    return ("attrs", tuple((k, v, _contents(v) if isinstance(v, _CONTAINERS) else None)
                           for k, v in items.items()))


#: How each mutable kind is pictured: (types, picture). The first match wins; a kind not
#: listed falls through to its ``__dict__``. ``None`` = never compared.
_PICTURES: tuple = (
    (_IMMUTABLE + (types.ModuleType, types.FunctionType, types.BuiltinFunctionType, types.MethodType,
                   logging.Logger, logging.LoggerAdapter), lambda value: None),
    ((dict,), lambda value: ("dict", tuple(value.items()))),
    ((list, bytearray), lambda value: ("seq", tuple(value))),
    ((set,), lambda value: ("set", frozenset(value))),
)


def _contents(value: Any) -> Any:
    """A shallow, identity-comparable picture of a mutable value; None when it is not compared."""

    picture = next((make for kinds, make in _PICTURES if isinstance(value, kinds)), _attrs_picture)
    return picture(value)


def _same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    if a[0] != b[0]:
        return False
    if a[0] == "set":
        return a[1] == b[1]
    left, right = a[1], b[1]
    if len(left) != len(right):
        return False
    for x, y in zip(left, right):
        if isinstance(x, tuple) and isinstance(y, tuple) and len(x) == len(y):
            if not all(p is q or (isinstance(p, tuple) and isinstance(q, tuple) and _same(p, q))
                       for p, q in zip(x, y)):
                return False
        elif x is not y:
            return False
    return True


def _owned_by_plugin(module: types.ModuleType, package: str, value: Any) -> bool:
    """Whether a global is state the package's import created (classes/objects), not an imported object."""

    if isinstance(value, type):
        return str(getattr(value, "__module__", "")).startswith(package)
    if isinstance(value, _CONTAINERS):
        return True
    owner = getattr(type(value), "__module__", "")
    return str(owner).startswith(package) and hasattr(value, "__dict__")


def _top_level_from_imports(module: types.ModuleType) -> list[tuple[str, str, str]]:
    """``(bound name, source module, source attr)`` for each module-level ``from X import a as b``."""

    path = getattr(module, "__file__", None)
    if not path:
        return []
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return []
    package = module.__name__ if hasattr(module, "__path__") else module.__name__.rpartition(".")[0]
    found = []

    def walk(body):
        for node in body:
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")
                    base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                    source = ".".join(base + ([node.module] if node.module else []))
                else:
                    source = node.module or ""
                for alias in node.names:
                    if alias.name != "*":
                        found.append((alias.asname or alias.name, source, alias.name))
            elif isinstance(node, (ast.If, ast.Try)):  # guarded imports still run at import time
                walk(node.body)
                for handler in getattr(node, "handlers", []):
                    walk(handler.body)
                walk(node.orelse)
                walk(getattr(node, "finalbody", []))

    walk(tree.body)
    return found


def _code_strings(module: types.ModuleType) -> set[str]:
    path = getattr(module, "__file__", None)
    if not path:
        return set()
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return set()
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and 0 < len(node.value) < 128}


def _holds_home(module: types.ModuleType, home: str) -> bool:
    if not home:
        return False
    needle = os.path.normcase(home)

    def hit(value):
        if isinstance(value, (str, PurePath)):
            return needle in os.path.normcase(os.fspath(value))
        return False

    for value in vars(module).values():
        if hit(value):
            return True
        if isinstance(value, dict) and any(hit(v) for v in value.values()):
            return True
        if isinstance(value, (list, tuple, set)) and any(hit(v) for v in value):
            return True
    return False


def _current_home() -> str:
    try:
        from hermes_constants import get_hermes_home
        return str(get_hermes_home())
    except Exception:
        return ""


def _snapshot(name: str, env_before: dict[str, str]) -> _Kept:
    prefix = name + "."
    modules = {n: m for n, m in list(sys.modules.items()) if n == name or n.startswith(prefix)}
    kept = _Kept(name=name, modules=modules, globals_={}, contents={}, captures=[], env={})
    home = _current_home()
    strings: set[str] = set()
    for mod_name, module in modules.items():
        if module is None:
            continue
        namespace = dict(vars(module))
        kept.globals_[mod_name] = namespace
        for key, value in namespace.items():
            if key.startswith("__") and key.endswith("__"):
                continue
            if _owned_by_plugin(module, name, value):
                picture = _contents(value)
                if picture is not None:
                    kept.contents[(mod_name, key)] = (value, picture)
        for bound, source, attr in _top_level_from_imports(module):
            if not (source == name or source.startswith(prefix)):
                kept.captures.append((mod_name, bound, source, attr))
        strings |= _code_strings(module)
        if _holds_home(module, home):
            kept.reasons.append(f"holds the test home: {mod_name}")
    for key in strings:  # a name that looks like an environment variable, set or not at import
        if key in env_before or _ENV_NAME.fullmatch(key):
            kept.env[key] = env_before.get(key)
    return kept


def _cold_reason(kept: _Kept) -> str | None:
    if kept.reasons:
        return kept.reasons[0]
    for key, value in kept.env.items():
        if os.environ.get(key) != value:
            return f"environment {key}"
    for mod_name, bound, source, attr in kept.captures:
        origin = sys.modules.get(source)
        if origin is None:
            continue
        sentinel = object()
        now = getattr(origin, attr, sentinel)
        if now is sentinel:
            continue  # a submodule bound by `from pkg import sub` that pkg does not expose as an attribute
        if now is not kept.globals_[mod_name].get(bound, sentinel):
            return f"patched capture {source}.{attr}"
    for (mod_name, key), (value, picture) in kept.contents.items():
        if not _same(_contents(value), picture):
            return f"mutated {mod_name}.{key}"
    return None


def _reinstall(kept: _Kept) -> types.ModuleType:
    from hermes_cli import plugins_loader

    plugins_loader._evict_modules(kept.name)
    for mod_name, module in kept.modules.items():
        namespace = vars(module)
        saved = kept.globals_[mod_name]
        for key in [k for k in namespace if k not in saved]:
            del namespace[key]
        namespace.update(saved)
        sys.modules[mod_name] = module
    return kept.modules[kept.name]


def _bypassed() -> bool:
    try:
        from tests._downstream import plugin_discovery_cache
    except Exception:
        return False
    return plugin_discovery_cache._bypassed()


def _keeping_load(real):
    def _load_directory_module(self, manifest, *, module_name=None):
        if not enabled() or getattr(manifest, "source", None) != "bundled" or _bypassed():
            return real(self, manifest, module_name=module_name)
        name = module_name or self._directory_module_name(manifest)
        init = os.path.normcase(os.path.abspath(os.path.join(str(manifest.path), "__init__.py")))
        try:
            stamp = os.stat(init).st_mtime_ns
        except OSError:
            stamp = None
        key = (name, init)
        with _LOCK:
            kept = _KEPT.get(key)
            if kept is not None and kept.stamp == stamp:
                reason = _cold_reason(kept)
                if reason is None:
                    _STATE["hits"] += 1
                    return _reinstall(kept)
                _COLD_REASONS[reason] = _COLD_REASONS.get(reason, 0) + 1
            env_before = dict(os.environ)
            module = real(self, manifest, module_name=name)
            fresh = _snapshot(name, env_before)
            fresh.stamp = stamp
            _KEPT[key] = fresh
            _STATE["misses"] += 1
            return module

    _load_directory_module.__wrapped__ = real
    setattr(_load_directory_module, _MARK, True)
    return _load_directory_module


def install_if_imported() -> bool:
    plugins = sys.modules.get("hermes_cli.plugins")
    if plugins is None:
        return False
    manager = plugins.PluginManager
    if not getattr(manager._load_directory_module, _MARK, False):
        manager._load_directory_module = _keeping_load(manager._load_directory_module)
    return True


@pytest.fixture(autouse=True)
def _plugin_module_keep():
    """Autouse: install the (opt-in, default OFF) bundled-module keep once the plugin stack is imported."""

    if enabled():
        install_if_imported()
    yield
