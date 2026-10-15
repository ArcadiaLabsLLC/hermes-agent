"""Handlers bound by NAME, imported when their verb is parsed.

The tree binds every ``func=`` (and the one lazy ``type=``) as a
:class:`LazyHandler` — a module path and an attribute — so building
``hermes harness`` imports argparse wiring only. :class:`LazyHandlerParser`, the
class of every parser under ``harness``, resolves its own ``func`` default when
argparse descends into it, so parsing imports exactly the chosen verb's module
and ``args.func`` is that module's own function. Before this, the tree imported
every handler module at build time (~570 modules, 1-2 s, for any ``hermes``
invocation that attached the harness parser).

One spelling, ``part = lazy_module("pkg.mod")`` then ``func=part._cmd_x``, with a
literal module path so the bundle-closure walk (``scripts/bundle_profile_closure.py``)
reads it as an import.

A misspelled name is not caught by the import any more; the runtime gate
``tests/hermes_cli/test_harness_parts_namespace.py`` resolves every lazy
binding in the tree and fails on the first one that does not.
"""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Callable
from typing import Any

__layer__ = "wiring"
__all__ = ["LazyHandler", "LazyHandlerParser", "lazy_module", "resolve_lazy"]


class LazyHandler:
    """A callable named by ``module`` + ``name``; imported on first call or parse.

    ``__module__`` / ``__name__`` / ``__qualname__`` name the TARGET, so a reader
    of an unparsed tree (the contract dump, a census) sees the handler it will
    become. ``wrappers`` are applied, in order, to the resolved function — the
    plugin door's ``_harness_entry`` rides here instead of importing the target.
    """

    def __init__(self, module: str, name: str, wrappers: tuple[Callable[[Any], Any], ...] = ()) -> None:
        self.__module__ = module
        self.__name__ = name
        self.__qualname__ = name
        self.wrappers = wrappers

    def resolve(self) -> Callable[..., Any]:
        target = getattr(importlib.import_module(self.__module__), self.__name__)
        for wrap in self.wrappers:
            target = wrap(target)
        return target

    def wrapped(self, wrapper: Callable[[Any], Any]) -> "LazyHandler":
        return LazyHandler(self.__module__, self.__name__, (*self.wrappers, wrapper))

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.resolve()(*args, **kwargs)

    def __repr__(self) -> str:
        return f"<lazy {self.__module__}:{self.__name__}>"


def resolve_lazy(value: Any) -> Any:
    """``value`` itself, or the function a :class:`LazyHandler` names."""

    return value.resolve() if isinstance(value, LazyHandler) else value


class _LazyModule:
    """``import module`` without the import: ``proxy.name`` is a :class:`LazyHandler`."""

    def __init__(self, module: str) -> None:
        self._module = module

    def __getattr__(self, name: str) -> LazyHandler:
        if name.startswith("__"):
            raise AttributeError(name)
        return LazyHandler(self._module, name)


def lazy_module(module: str) -> Any:
    """``import module`` without the import (see the module docstring)."""

    return _LazyModule(module)


class LazyHandlerParser(argparse.ArgumentParser):
    """An ``ArgumentParser`` that imports its own handler when argparse enters it.

    ``_SubParsersAction`` calls ``parse_known_args`` on the ONE subparser the argv
    chose, so only that verb's ``func`` is resolved; nested ``add_subparsers``
    inherit the class (argparse defaults ``parser_class`` to ``type(self)``).
    """

    def parse_known_args(self, args=None, namespace=None):  # type: ignore[override]
        func = self._defaults.get("func")
        if isinstance(func, LazyHandler):
            self._defaults["func"] = func.resolve()
        return super().parse_known_args(args, namespace)
