"""The agents a FRESH harness root starts with: Neko Mission Lead and Base Agent.

Owner rulings: "new installs default agent should be neko mission lead"
(2026-11-18, ``RT-FRESH-INSTALL-SEEDS-NEKO``); only Base Agent and Neko Mission
Lead ship, and they always update (2026-11-19, ``RT-BUNDLED-AGENTS-LIVE-IN-THE-BUILD``).
Personas otherwise stay data; this seed is narrow on purpose:

* it runs only when the roster (persisted store merged over config records) is
  EMPTY — a root holding any persona gains nothing;
* it writes REFERENCES (``origin: "eternia"``): the definition and Neko's SOUL are
  read from the build on every load (``agent_runtime.bundled_agents``), so a later
  build updates them with no store write;
* it never overwrites: a ``neko`` profile this seed did not stage keeps Neko out;
* it ships no model and no provider — the user's own sign-in decides those;
* Base's profile is Eternia's bundled ``base`` profile: never staged or touched here.

Eternia's console selects ``neko_supervisor`` first whenever it exists. Caller:
``hermes harness init`` (``hermes_cli/harness_parts/init_commands.py::_cmd_init``),
before the default scope is reconciled so both join it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from hermes_cli.profiles import get_profile_dir
from hermes_cli.profiles_initialization import finish_profile_layout

from . import yaml_io
from .bundled_agents import reference_record, shipped_agent
from .config import ensure_persisted_personas
from .config.schema import AgentRuntimeConfig
from .locks import agent_create_lock
from .models import AgentPersona
from .persona_seed_defaults import persona_profile_homes, seed_persona_profile
from .store import AgentStore

__layer__ = "stores"
__all__ = ["BASE_PERSONA_ID", "NEKO_PERSONA_ID", "NEKO_PROFILE", "seed_fresh_install_persona"]

BASE_PERSONA_ID = "base"
NEKO_PERSONA_ID = "neko_supervisor"
NEKO_PROFILE = "neko"
_SOUL_SOURCE = Path(__file__).resolve().parent / "seed_souls" / "neko.md"
#: Written into the profile this seed stages, so a run interrupted between the
#: profile publish and the record save finishes on the next init instead of
#: refusing a profile it cannot tell from a user's own.
_SEED_MARKER = ".eternia-seeded-persona"


def _stage_neko_profile(home: Path) -> None:
    """Publish the ``neko`` profile atomically: built in a sibling temp dir, then renamed."""

    home.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=home.parent, prefix=f".{home.name}-") as temp:
        stage = Path(temp) / "profile"
        stage.mkdir()
        (stage / "config.yaml").write_text(yaml_io.dump({}), encoding="utf-8")
        finish_profile_layout(
            stage, no_skills=False, clone_all=False, description=None,
            soul=_SOUL_SOURCE.read_text(encoding="utf-8"),
        )
        (stage / _SEED_MARKER).write_text(NEKO_PERSONA_ID, encoding="utf-8")
        os.rename(stage, home)


def _seeded_by_us(home: Path) -> bool:
    marker = home / _SEED_MARKER
    return (
        not home.is_symlink() and not marker.is_symlink() and marker.is_file()
        and marker.read_text(encoding="utf-8") == NEKO_PERSONA_ID
    )


def seed_fresh_install_persona(cfg: AgentRuntimeConfig) -> list[AgentPersona]:
    """Reference the shipped agents on a root with no personas; ``[]`` when nothing was seeded."""

    if ensure_persisted_personas(cfg):
        return []
    with agent_create_lock(f"fresh-install-{NEKO_PERSONA_ID}"):
        if ensure_persisted_personas(cfg):
            return []
        store = AgentStore()
        seeded: list[AgentPersona] = []
        home = get_profile_dir(NEKO_PROFILE)
        if home.exists() or home.is_symlink():
            neko_ok = _seeded_by_us(home)
        else:
            _stage_neko_profile(home)
            neko_ok = True
        if neko_ok:
            neko = store.save(reference_record(shipped_agent(NEKO_PERSONA_ID)))
            seeded.append(neko)
            # The owner-ruled config seed keys every persona create fills (2026-10-03),
            # through their one writer, as ``persona_profiles.promote_profile_to_persona`` does.
            for profile_home in persona_profile_homes([neko]):
                seed_persona_profile(profile_home)
        seeded.append(store.save(reference_record(shipped_agent(BASE_PERSONA_ID))))
    return seeded
