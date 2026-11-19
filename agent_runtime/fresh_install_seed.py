"""The one persona a FRESH harness root starts with: Neko Mission Lead.

Owner ruling 2026-11-18 (``RT-FRESH-INSTALL-SEEDS-NEKO``): "new installs default
agent should be neko mission lead". Bundled persona seeding was retired on
2026-08-02 and personas stay data; this is the single exception, and it is
narrow on purpose:

* it runs only when the roster (persisted store merged over config records) is
  EMPTY — a root holding any persona gains nothing;
* it never overwrites: an existing ``neko_supervisor`` record or a ``neko``
  profile this seed did not stage is left alone (the seed then does nothing);
* it ships no model and no provider — the user's own sign-in decides those;
* ``base`` is untouched: it stays the protocol-layer profile, resolved as before.

Eternia's console selects ``neko_supervisor`` first whenever it exists, so
creating the record is all a new install needs. Caller: ``hermes harness init``
(``hermes_cli/harness_parts/init_commands.py::_cmd_init``), before the default
scope is reconciled so Neko joins it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from hermes_cli.profiles import get_profile_dir
from hermes_cli.profiles_initialization import finish_profile_layout

from . import yaml_io
from .config import ensure_persisted_personas
from .config.schema import AgentRuntimeConfig
from .locks import agent_create_lock
from .models import AgentPersona, AutonomyLevel
from .persona_seed_defaults import persona_profile_homes, seed_persona_profile
from .store import AgentStore

__layer__ = "stores"
__all__ = ["NEKO_PERSONA_ID", "NEKO_PROFILE", "seed_fresh_install_persona"]

NEKO_PERSONA_ID = "neko_supervisor"
NEKO_PROFILE = "neko"
#: The canonical spelling of the ``alice_supervisor`` / ``neko_supervisor`` pair
#: (``personas.canonical_persona_id``): the terminal-envelope grant table keys on
#: it (``terminal_envelope.records.canonical_role``), and existing Neko records
#: carry it, so a grant written for Neko applies to the seeded one too.
_NEKO_ROLE = "alice_supervisor"
_NEKO_SKILLS = ("harness-runtime-model",)
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


def seed_fresh_install_persona(cfg: AgentRuntimeConfig) -> AgentPersona | None:
    """Create Neko Mission Lead on a root with no personas; ``None`` when nothing was seeded."""

    if ensure_persisted_personas(cfg):
        return None
    with agent_create_lock(f"fresh-install-{NEKO_PERSONA_ID}"):
        if ensure_persisted_personas(cfg):
            return None
        home = get_profile_dir(NEKO_PROFILE)
        if home.exists() or home.is_symlink():
            if not _seeded_by_us(home):
                return None
        else:
            _stage_neko_profile(home)
        saved = AgentStore().save(AgentPersona(
            id=NEKO_PERSONA_ID,
            display_name="Neko Mission Lead",
            role=_NEKO_ROLE,
            model=None,
            provider=None,
            api_mode=None,
            autonomy=AutonomyLevel.PROPOSE_ONLY,
            hermes_profile=NEKO_PROFILE,
            skills=list(_NEKO_SKILLS),
            soul_overlay_path="SOUL.md",
            include_profile_memory=True,
            include_core_context_files=False,
        ))
    # The owner-ruled config seed keys every persona create fills (2026-10-03),
    # through their one writer, as ``persona_profiles.promote_profile_to_persona`` does.
    for profile_home in persona_profile_homes([saved]):
        seed_persona_profile(profile_home)
    return saved
