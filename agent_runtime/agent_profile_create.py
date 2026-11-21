"""An agent's own profile home is made by upstream's one profile creator.

Row ``RT-AN-AGENT-COPY-OR-NEW-AGENT-GETS-ITS-PROFILE-FROM-THE-ONE-PROFILE-CREATOR``
(seen 2026-11-21, w1118a-onepath-profile, through ``runtime.agent.duplicate`` and
``runtime.persona.instance.create``): the duplicate and the independent copy each
staged a profile by hand and reused only ``finish_profile_layout``, so the steps
``hermes_cli.profiles.create_profile`` runs around it were skipped — a copy given a
name a ``hermes profile delete`` had tombstoned was born deleted (its turns refuse),
the memory provider was never told the profile exists, a running multiplexer was
never asked to serve it, and the s6 gateway service was never registered. Both doors
now call :func:`create_agent_profile`, which calls ``create_profile``.

The copy's model block travels through the creator's own launch-model seed: the seed
reads the ACTIVE home's ``config.yaml``, so the creator runs with the context-local
home (``set_hermes_home_override``; the profiles root is the process root and does not
move) pointed at a throwaway home whose ``config.yaml`` is the carried, credential-free
block (``persona_assignments.independent._carried_model_config``). The creator then
seeds exactly that, migrates it in its staging tree and publishes — never the head
home's model block, which may hold an inline key (upstream's later ``seed_model=False``
exists for that; the fork's ``create_profile`` predates it). Fresh, never
``clone_from``: a clone copies the source's ``.env`` and whole ``config.yaml``, and a
copy takes none of its source's sign-in (owner ruling 2026-11-19, ``agent_duplicate``).

After the creator returns, only what the fork alone knows is written: the owner marker
(``OWNER_FILE``) first, then the agent's own files through the caller's ``populate``. A
failure there moves the published home to the archive a failed independent create
uses (archive-never-delete), so the name is free again.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hermes_cli.profiles import create_profile, get_profile_dir, validate_profile_name
from hermes_constants import reset_hermes_home_override, set_hermes_home_override

from . import yaml_io

__layer__ = "stores"

__all__ = ["OWNER_FILE", "create_agent_profile", "free_profile_name"]

#: The marker an agent profile the fork made carries: who it was made for.
OWNER_FILE = ".eternia-agent-owner"
#: Where a fork-made profile goes when it is retired (never erased).
_RETIRED_PROFILES = ".retired-independent-agents"


def free_profile_name(base: str) -> str:
    """``base`` when it is a valid, unreserved profile id nobody holds; else ``base-<hex>``."""

    try:
        validate_profile_name(base)
    except ValueError:
        return f"{base[:55]}-{uuid.uuid4().hex[:8]}"
    home = get_profile_dir(base)
    return base if not (home.exists() or home.is_symlink()) else f"{base[:55]}-{uuid.uuid4().hex[:8]}"


def _retire_profile_home(home: Path) -> None:
    """Move ``home`` into the retired-agents archive."""

    archive = home.parent / _RETIRED_PROFILES / uuid.uuid4().hex
    archive.mkdir(parents=True)
    os.replace(home, archive / "profile")


def _create_seeded(profile: str, config: dict[str, Any], soul: str | None) -> Path:
    with tempfile.TemporaryDirectory(prefix="agent-model-seed-") as seed_home:
        if config:
            (Path(seed_home) / "config.yaml").write_text(yaml_io.dump(config), encoding="utf-8")
        # MUTATION: drop this override -> all 8 tests of test_agent_copy_keeps_its_model_endpoint.py
        # redden: the creator seeds the head home's model block, inline key and all.
        token = set_hermes_home_override(seed_home)
        try:
            return create_profile(profile, soul=soul)
        finally:
            reset_hermes_home_override(token)


def create_agent_profile(
    profile: str, *, owner: str, config: dict[str, Any], soul: str | None,
    populate: Callable[[Path], None] | None = None,
) -> Path:
    """Make ``profile`` through ``create_profile`` seeded with ``config``, then mark and fill it."""

    home = _create_seeded(profile, config, soul)
    try:
        (home / OWNER_FILE).write_text(owner, encoding="utf-8")
        if populate is not None:
            populate(home)
    except BaseException:
        _retire_profile_home(home)
        raise
    return home
