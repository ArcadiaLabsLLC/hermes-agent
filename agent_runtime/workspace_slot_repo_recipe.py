"""A repository's own setup recipe: ``.eternia/setup/recipe.json`` in the slot's checkout, read here only.

Plan ``docs/agent-runtime-harness/planned/slot-setup-recipe-2026-11-15.md`` §2 (owner rulings
2026-11-15/16). The recipe lives IN THE REPOSITORY, cloned and versioned with it; hermes never
writes it and never reads another computer's copy. :func:`read_recipe` is its one reader: one
closed shape, version 1, per platform —

* ``platforms.<this computer's platform>`` gives this computer's ``tools`` and ``script``;
  ``env_keys`` and ``dotenv`` are shared by the platforms the file lists. A platform the file
  does not list reads as NO recipe, keys included.
* **Blank by default**: no file, an unbound slot, or a file that is not version 1 answers a
  :class:`RecipeRead` with ``blank`` (``no_recipe`` / ``not_cloned`` / ``unreadable``) and its
  ``why``. Nothing is derived from the slot declaration to fill the gap.
* **Bounds**: ``recipe.json`` at most :data:`MAX_RECIPE_BYTES`, a script at most
  :data:`MAX_SCRIPT_BYTES` and only a plain file name inside ``.eternia/setup/``
  (``script_outside_setup`` otherwise); a credential-shaped ``hint`` or a ``url`` with userinfo
  makes the file unreadable (``credential_in_step``).

Item ids are derived and stable: ``tool:<name>``, ``env_key:<KEY>``, ``dotenv``, ``script``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .workspace_slot_recipe import text_carries_credential, url_carries_credential

__layer__ = "stores"

SETUP_DIR = Path(".eternia") / "setup"
RECIPE_FILE = SETUP_DIR / "recipe.json"
RECIPE_VERSION = 1
MAX_RECIPE_BYTES = 64 * 1024
MAX_SCRIPT_BYTES = 256 * 1024

PLATFORM_WINDOWS = "windows"
PLATFORM_MACOS = "macos"
PLATFORM_LINUX = "linux"
PLATFORMS = (PLATFORM_WINDOWS, PLATFORM_MACOS, PLATFORM_LINUX)

BLANK_NO_RECIPE = "no_recipe"
BLANK_NOT_CLONED = "not_cloned"
BLANK_UNREADABLE = "unreadable"

#: Why an unreadable file is unreadable (``RecipeRead.why`` when ``blank`` is ``unreadable``).
WHY_TOO_LARGE = "too_large"
WHY_NOT_JSON = "not_json"
WHY_UNSUPPORTED_VERSION = "unsupported_version"
WHY_INVALID_SHAPE = "invalid_shape"
WHY_SCRIPT_OUTSIDE_SETUP = "script_outside_setup"
WHY_SCRIPT_MISSING = "script_missing"
WHY_SCRIPT_TOO_LARGE = "script_too_large"
WHY_CREDENTIAL_IN_STEP = "credential_in_step"

ITEM_TOOL = "tool"
ITEM_ENV_KEY = "env_key"
ITEM_DOTENV = "dotenv"
ITEM_SCRIPT = "script"

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_TOOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
_VERSION_RE = re.compile(r"^[0-9]{1,9}(?:\.[0-9]{1,9})*$")
_SCRIPT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_TOP_FIELDS = frozenset({"version", "env_keys", "dotenv", "platforms"})
_PLATFORM_FIELDS = frozenset({"script", "tools"})
_TOOL_FIELDS = frozenset({"name", "min_version", "hint", "url"})
_KEY_FIELDS = frozenset({"key", "secret", "hint", "url"})
_DOTENV_FIELDS = frozenset({"path", "example", "keys"})


class _Unreadable(ValueError):
    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


@dataclass(frozen=True)
class RepoRecipe:
    """This computer's platform's part of one ``recipe.json``."""

    platform: str
    tools: tuple[dict[str, Any], ...]
    env_keys: tuple[dict[str, Any], ...]
    dotenv: dict[str, Any] | None
    script: str | None

    @property
    def secret_keys(self) -> frozenset[str]:
        rows = list(self.env_keys) + list((self.dotenv or {}).get("keys") or [])
        return frozenset(row["key"] for row in rows if row.get("secret"))

    @property
    def keys(self) -> frozenset[str]:
        """Every key the recipe names: its env keys and its ``.env`` keys."""

        return frozenset(row["key"] for row in [*self.env_keys, *((self.dotenv or {}).get("keys") or [])])

    def script_path(self, checkout: Path) -> Path | None:
        return None if self.script is None else Path(checkout) / SETUP_DIR / self.script


@dataclass(frozen=True)
class RecipeRead:
    """One slot's recipe on this computer: a :class:`RepoRecipe`, or ``blank`` with its ``why``."""

    platform: str
    recipe: RepoRecipe | None = None
    blank: str | None = None
    why: str | None = None

    @property
    def secret_keys(self) -> frozenset[str]:
        return self.recipe.secret_keys if self.recipe else frozenset()

    @property
    def keys(self) -> frozenset[str]:
        return self.recipe.keys if self.recipe else frozenset()


def this_platform() -> str:
    """This computer's platform word: ``windows``, ``macos`` or ``linux``."""

    if sys.platform == "win32":
        return PLATFORM_WINDOWS
    return PLATFORM_MACOS if sys.platform == "darwin" else PLATFORM_LINUX


def _closed(value: Any, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - fields:
        raise _Unreadable(WHY_INVALID_SHAPE)
    return value


def _prose(row: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    hint, url = row.get("hint"), row.get("url")
    if hint is not None:
        if not isinstance(hint, str):
            raise _Unreadable(WHY_INVALID_SHAPE)
        if text_carries_credential(hint):
            raise _Unreadable(WHY_CREDENTIAL_IN_STEP)
        out["hint"] = hint
    if url is not None:
        if not isinstance(url, str) or not re.match(r"^https?://\S+$", url):
            raise _Unreadable(WHY_INVALID_SHAPE)
        if url_carries_credential(url):
            raise _Unreadable(WHY_CREDENTIAL_IN_STEP)
        out["url"] = url
    return out


def _key_rows(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise _Unreadable(WHY_INVALID_SHAPE)
    rows, seen = [], set()
    for entry in value:
        entry = _closed(entry, _KEY_FIELDS)
        key = entry.get("key")
        if not isinstance(key, str) or not _KEY_RE.match(key) or key in seen or not isinstance(entry.get("secret", False), bool):
            raise _Unreadable(WHY_INVALID_SHAPE)
        seen.add(key)
        rows.append(_prose(entry, {"key": key, "secret": bool(entry.get("secret", False))}))
    return tuple(rows)


def _inside(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and ".." not in value.replace("\\", "/").split("/")
            and not Path(value).is_absolute() and not value.startswith(("/", "\\")))


def _dotenv(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    value = _closed(value, _DOTENV_FIELDS)
    path, example = value.get("path", ".env"), value.get("example")
    if not _inside(path) or (example is not None and not _inside(example)):
        raise _Unreadable(WHY_INVALID_SHAPE)
    return {"path": path, "example": example, "keys": list(_key_rows(value.get("keys")))}


def _tools(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise _Unreadable(WHY_INVALID_SHAPE)
    rows, seen = [], set()
    for entry in value:
        entry = _closed(entry, _TOOL_FIELDS)
        name, minimum = entry.get("name"), entry.get("min_version")
        if not isinstance(name, str) or not _TOOL_RE.match(name) or name in seen:
            raise _Unreadable(WHY_INVALID_SHAPE)
        if minimum is not None and (not isinstance(minimum, str) or not _VERSION_RE.match(minimum)):
            raise _Unreadable(WHY_INVALID_SHAPE)
        seen.add(name)
        rows.append(_prose(entry, {"name": name, "min_version": minimum}))
    return tuple(rows)


def _script(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SCRIPT_RE.match(value) or value in (".", ".."):
        # A separator, a parent step or an absolute path: the script lives in ``.eternia/setup/`` only.
        raise _Unreadable(WHY_SCRIPT_OUTSIDE_SETUP)
    return value


def _resolves_inside(path: Path, folder: Path) -> bool:
    try:
        return path.resolve().is_relative_to(folder.resolve())
    except (OSError, ValueError):
        return False


def parse_recipe(text: str, platform: str) -> RepoRecipe | None:
    """``platform``'s recipe from ``recipe.json`` text; None when the file lists no such platform.

    Raises :class:`_Unreadable` on anything that is not the closed version-1 shape.
    """

    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise _Unreadable(WHY_NOT_JSON) from exc
    if not isinstance(payload, dict):
        raise _Unreadable(WHY_INVALID_SHAPE)
    if payload.get("version") != RECIPE_VERSION or isinstance(payload.get("version"), bool):
        raise _Unreadable(WHY_UNSUPPORTED_VERSION)
    payload = _closed(payload, _TOP_FIELDS)
    platforms = payload.get("platforms")
    if not isinstance(platforms, dict) or set(platforms) - set(PLATFORMS):
        raise _Unreadable(WHY_INVALID_SHAPE)
    sections = {name: _closed(body, _PLATFORM_FIELDS) for name, body in platforms.items()}
    parsed = {name: (_tools(body.get("tools")), _script(body.get("script"))) for name, body in sections.items()}
    env_keys, dotenv = _key_rows(payload.get("env_keys")), _dotenv(payload.get("dotenv"))
    if platform not in parsed:
        return None
    tools, script = parsed[platform]
    return RepoRecipe(platform, tools, env_keys, dotenv, script)


def read_recipe(checkout: Path | str | None, platform: str) -> RecipeRead:
    """THE reader of a repository's setup recipe: ``platform``'s part of ``checkout``'s ``recipe.json``."""

    if checkout is None or not Path(checkout).is_dir():
        return RecipeRead(platform, blank=BLANK_NOT_CLONED, why=BLANK_NOT_CLONED)
    root = Path(checkout)
    target = root / RECIPE_FILE
    if not target.is_file():
        return RecipeRead(platform, blank=BLANK_NO_RECIPE, why=BLANK_NO_RECIPE)
    try:
        if not _resolves_inside(target, root):
            raise _Unreadable(WHY_INVALID_SHAPE)
        if target.stat().st_size > MAX_RECIPE_BYTES:
            raise _Unreadable(WHY_TOO_LARGE)
        recipe = parse_recipe(target.read_text(encoding="utf-8"), platform)
        if recipe is None:
            return RecipeRead(platform, blank=BLANK_NO_RECIPE, why=f"no {platform} recipe")
        script = recipe.script_path(root)
        if script is not None:
            if not script.is_file() or not _resolves_inside(script, root / SETUP_DIR):
                raise _Unreadable(WHY_SCRIPT_MISSING if not script.exists() else WHY_SCRIPT_OUTSIDE_SETUP)
            if script.stat().st_size > MAX_SCRIPT_BYTES:
                raise _Unreadable(WHY_SCRIPT_TOO_LARGE)
    except _Unreadable as exc:
        return RecipeRead(platform, blank=BLANK_UNREADABLE, why=exc.why)
    except (OSError, UnicodeDecodeError):
        return RecipeRead(platform, blank=BLANK_UNREADABLE, why=WHY_NOT_JSON)
    return RecipeRead(platform, recipe=recipe)


def read_script(checkout: Path | str, recipe: RepoRecipe) -> dict[str, Any] | None:
    """``{path, sha256, text}`` of ``recipe``'s script in ``checkout`` (bounded, contained); None when it has none."""

    path = recipe.script_path(Path(checkout))
    if path is None or not path.is_file() or not _resolves_inside(path, Path(checkout) / SETUP_DIR):
        return None
    data = path.read_bytes()[: MAX_SCRIPT_BYTES + 1]
    if len(data) > MAX_SCRIPT_BYTES:
        return None
    return {"path": (SETUP_DIR / str(recipe.script)).as_posix(), "sha256": hashlib.sha256(data).hexdigest(),
            "text": data.decode("utf-8", "replace")}


def slot_recipe(workspace_id: str | None, slot: str, platform: str | None = None) -> RecipeRead:
    """The recipe of ``slot``'s checkout bound on THIS computer (blank ``not_cloned`` when unbound)."""

    from .workspace_slots import bound_path

    return read_recipe(bound_path(slot, workspace_id=workspace_id), platform or this_platform())


__all__ = [
    "BLANK_NOT_CLONED",
    "BLANK_NO_RECIPE",
    "BLANK_UNREADABLE",
    "PLATFORMS",
    "RecipeRead",
    "RepoRecipe",
    "parse_recipe",
    "read_recipe",
    "read_script",
    "slot_recipe",
    "this_platform",
]
