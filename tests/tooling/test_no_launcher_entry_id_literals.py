"""No hermes code names a Launcher entry id — intents come only from the Launcher's list.

One-action-layer R10 (launcher ``docs/embedded_hermes/subsystems/ONE_ACTION_LAYER_2026-10-10.md``
§3, slice S17): the runtime learns what the Launcher can do ONLY from
``launcher.app_functions.list``. A ``launcher.<area>.<verb>`` literal anywhere
else is a second, unlisted copy of the Launcher's catalog — it survives the
entry being renamed, gated or retired, and it lets hermes offer an intent the
Launcher did not list on this connection.

This is a "must never be written" rule, so a source walk is the right shape and
over-approximation is the safe direction: comments and docstrings count.
Population: every tracked source file (and model-facing prose under the skill
and plugin roots) outside the test trees and ``docs/`` — a test's fake Launcher
must name ids, and docs describe the wire.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import PurePosixPath

from scripts import god_file_probe as probe

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

_SOURCE_SUFFIXES = frozenset({
    ".py", ".pyi", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".rs", ".go", ".sh", ".ps1",
    ".yaml", ".yml", ".toml", ".json", ".txt", ".j2", ".jinja", ".tmpl",
})
#: Prose the model reads as instructions: a skill teaching an id is the same leak.
_PROSE_ROOTS = ("skills/", "optional-skills/", "plugins/")
_EXCLUDED_ROOTS = ("docs/", "Harness_Brain/", "website/")
_TEST_DIRS = frozenset({"tests", "tests-js", "__tests__", "test"})


def entry_ids(text: str) -> set[str]:
    return set(ENTRY_ID.findall(text))


def _in_population(path: str) -> bool:
    pure = PurePosixPath(path)
    if path.startswith(_EXCLUDED_ROOTS) or _TEST_DIRS.intersection(pure.parts[:-1]):
        return False
    name = pure.name
    if name.startswith("test_") or name.endswith("_test.py") or ".test." in name or ".spec." in name:
        return False
    return pure.suffix in _SOURCE_SUFFIXES or (pure.suffix == ".md" and path.startswith(_PROSE_ROOTS))


def _population() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=probe.ROOT, capture_output=True, check=True)
    return sorted(p for p in out.stdout.decode("utf-8").split("\0")
                  if p and _in_population(p) and (probe.ROOT / p).is_file())


def _found() -> set[tuple[str, str]]:
    found = set()
    for path in _population():
        text = (probe.ROOT / path).read_text(encoding="utf-8", errors="ignore")
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
