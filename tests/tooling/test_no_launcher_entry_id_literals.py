"""No hermes code names a Launcher entry id — intents come only from the Launcher's list.

One-action-layer R10 (launcher ``docs/embedded_hermes/subsystems/ONE_ACTION_LAYER_2026-10-10.md``
§3, slice S17): the runtime learns what the Launcher can do ONLY from
``launcher.app_functions.list``. A ``launcher.<area>.<verb>`` literal anywhere
else is a second, unlisted copy of the Launcher's catalog — it survives the
entry being renamed, gated or retired, and it lets hermes offer an intent the
Launcher did not list on this connection.

This is a "must never be written" rule, so a source walk is the right shape and
over-approximation is the safe direction: comments and docstrings count.
Population (shared with the tool-name fence, ``_launcher_literals.py``): every
tracked source file (and model-facing prose under the skill and plugin roots)
outside the test trees and ``docs/`` — a test's fake Launcher must name ids,
and docs describe the wire.
"""

from __future__ import annotations

import re

import pytest

from tests.tooling._launcher_literals import population_texts

pytestmark = pytest.mark.gate

#: An entry id: ``launcher.`` and at least two dotted segments. ``launcher.pid``
#: and ``launcher.sh`` (file names) have one, and are not ids; ``launcher.parent.name``
#: is a ``Path`` named ``launcher`` walking up (upstream ``hermes_cli/install_state.py``
#: at v0.22.2), and no entry id starts with ``parent``.
ENTRY_ID = re.compile(r"(?<![\w.])launcher\.(?!parent\.)[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")

#: (path, id) -> why it may be written. Protocol only; never an intent.
ALLOWED: dict[tuple[str, str], str] = {
    ("agent_runtime/launcher_app_functions.py", "launcher.app_functions.list"):
        "LIST_METHOD — the discovery request itself, the one id the runtime must know",
}


def entry_ids(text: str) -> set[str]:
    return set(ENTRY_ID.findall(text))


def _found() -> set[tuple[str, str]]:
    found = set()
    for path, text in population_texts():
        if "launcher." in text:
            found.update((path, ident) for ident in entry_ids(text))
    return found


def test_the_pattern_sees_an_id_and_not_a_file_name():
    assert entry_ids('m = "launcher.settings.set"') == {"launcher.settings.set"}
    assert entry_ids("launcher.media.playback.state") == {"launcher.media.playback.state"}
    assert entry_ids('open(sd / "launcher.pid"); Path("launcher.sh"); "launcher."') == set()
    assert entry_ids("self.launcher.parent.mkdir()") == set()
    assert entry_ids('launcher.parent.name == "bin" and launcher.parent.parent.name') == set()
    assert entry_ids("launcher.parental.controls") == {"launcher.parental.controls"}


def test_no_launcher_entry_id_outside_the_allow_list():
    found = _found()
    leaks = sorted(f"{path}: {ident}" for path, ident in found - set(ALLOWED))
    assert not leaks, (
        "hermes names a Launcher entry id outside the listed catalog (R10). Read the "
        "intent from launcher.app_functions.list, or — if it is protocol — add it to "
        "ALLOWED with its reason:\n  " + "\n  ".join(leaks)
    )
    # Positive control: the walk reached the one allowed file and the pattern
    # matched there, so an empty ``leaks`` is not an empty walk.
    stale = sorted(f"{path}: {ident}" for path, ident in set(ALLOWED) - found)
    assert not stale, "ALLOWED names an id the tree no longer writes:\n  " + "\n  ".join(stale)
