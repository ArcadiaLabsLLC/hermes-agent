"""Vendor the Launcher's app-function catalog export into the hermes test fixture.

R10 (``docs/agent-runtime-harness/planned/p10-agent-2026-10-19.md`` §2): hermes never
derives a Launcher tool name; it reads ``launcher.app_functions.list`` at runtime. The
source gates still need the catalog to know what a leaked name looks like, so the
Launcher exports it (``EterniaLauncher/docs/embedded_hermes/generated/app_function_catalog.json``,
written by a Launcher test through ``appFunctionToolName``) and this script copies it to
``tests/fixtures/launcher_app_functions_catalog.json``, stamping the Launcher commit it
came from and printing what changed.

Run it at the weekly sync sitting and whenever the Launcher's catalog row says an entry
changed::

    python scripts/vendor_launcher_catalog.py <launcher>/docs/embedded_hermes/generated/app_function_catalog.json

``--launcher <checkout>`` names the Launcher checkout whose ``HEAD`` is stamped when the
export does not sit inside it. The pinning tests are
``tests/agent_runtime/test_launcher_catalog_fixture_parses.py`` and
``tests/tooling/test_no_launcher_tool_name_literals.py``.

The project-folder rule spec (Eternia ``packages/eternia_file_tree_spec/spec/``, row
``MC-PHONE-FILES-BOTH-LOCAL-READERS-FOLLOW-ONE-RULE-SPEC``) is vendored the same way, as a
generated mirror, never a hand copy::

    python scripts/vendor_launcher_catalog.py --file-tree-spec <launcher>/packages/eternia_file_tree_spec/spec

It replaces ``tests/fixtures/file_tree_spec/`` with the spec folder's files and writes
``PIN.json`` (the Launcher commit, each file's sha256 and :func:`spec_digest` over them).
``tests/agent_runtime/test_project_files_spec_mirror.py`` reds a hand edit of
the mirror, and a Launcher spec that moved without being vendored here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone, UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "launcher_app_functions_catalog.json"
FILE_TREE_SPEC = ROOT / "tests" / "fixtures" / "file_tree_spec"
SPEC_PIN = "PIN.json"

#: The fixture's per-entry keys, in order, and the type(s) each must carry. The Launcher
#: exports ``guidance_sha256: null`` for an entry with no guidance text (since its
#: 2026-10-21 export).
ENTRY_FIELDS: dict[str, type | tuple[type, ...]] = {
    "id": str,
    "name": str,
    "read_only": bool,
    "always_loaded": bool,
    "reach": str,
    "guidance_sha256": (str, type(None)),
}


def normalize_entries(raw: object) -> list[dict]:
    """The export's entries reduced to ``ENTRY_FIELDS``, sorted by id; ValueError on a bad shape."""

    entries = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or not entries:
        raise ValueError("the export carries no entries list")
    out: dict[str, dict] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"entry {index} is not an object")
        kept = {}
        for field, kind in ENTRY_FIELDS.items():
            value = entry.get(field)
            if not isinstance(value, kind):
                names = "/".join(k.__name__ for k in (kind if isinstance(kind, tuple) else (kind,)))
                raise ValueError(f"entry {index} ({entry.get('id')!r}): {field} is not a {names}")
            kept[field] = value
        if kept["id"] in out:
            raise ValueError(f"entry id {kept['id']!r} appears twice")
        out[kept["id"]] = kept
    return [out[key] for key in sorted(out)]


def entry_delta(old: list[dict], new: list[dict]) -> list[str]:
    """One line per added, removed or changed entry id."""

    before = {e["id"]: e for e in old}
    after = {e["id"]: e for e in new}
    lines = [f"+ {key}" for key in sorted(after.keys() - before.keys())]
    lines += [f"- {key}" for key in sorted(before.keys() - after.keys())]
    for key in sorted(before.keys() & after.keys()):
        changed = [f for f in ENTRY_FIELDS if before[key].get(f) != after[key].get(f)]
        if changed:
            lines.append(f"~ {key} ({', '.join(changed)})")
    return lines


def launcher_head(checkout: Path) -> str:
    result = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ValueError(f"{checkout} is not a git checkout: {result.stderr.strip()}")
    return result.stdout.strip()


def build_fixture(raw: object, source_commit: str) -> dict:
    """The fixture; an export that stamps its own 40-hex ``source_commit`` keeps it."""

    stamped = raw.get("source_commit") if isinstance(raw, dict) else None
    if isinstance(stamped, str) and len(stamped) == 40:
        source_commit = stamped
    exported_at = raw.get("exported_at") if isinstance(raw, dict) else None
    if not isinstance(exported_at, str) or not exported_at:
        exported_at = datetime.now(UTC).date().isoformat()
    return {"source_commit": source_commit, "exported_at": exported_at,
            "entries": normalize_entries(raw)}


def spec_files(folder: Path) -> dict[str, str]:
    """Every file of a spec folder but the pin, by ``/``-relative path, to its sha256."""

    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*"))
            if path.is_file() and path.relative_to(folder).as_posix() != SPEC_PIN}


def spec_digest(files: dict[str, str]) -> str:
    """One sha256 over a spec folder's ``{path: sha256}``, in path order."""

    joined = "".join(f"{path}\0{digest}\n" for path, digest in sorted(files.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def vendor_file_tree_spec(source: Path, out: Path, source_commit: str) -> dict:
    """Replace ``out`` with the spec folder ``source`` and its pin; the pin written."""

    if not (source / "rules.json").is_file() or not (source / "cases").is_dir():
        raise ValueError(f"{source} is not the rule spec folder (no rules.json and cases/)")
    files = spec_files(source)
    if out.exists():
        shutil.rmtree(out)
    for relative in files:
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / relative).read_bytes())
    pin = {"source_commit": source_commit, "sha256": spec_digest(files), "files": files}
    (out / SPEC_PIN).write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8", newline="\n")
    return pin


def _main_file_tree_spec(source: Path, launcher: Path | None, out: Path) -> int:
    old = {}
    if (out / SPEC_PIN).is_file():
        old = json.loads((out / SPEC_PIN).read_text(encoding="utf-8")).get("files", {})
    pin = vendor_file_tree_spec(source, out, launcher_head(launcher or source))
    changed = [f"+ {p}" for p in sorted(pin["files"].keys() - old.keys())]
    changed += [f"- {p}" for p in sorted(old.keys() - pin["files"].keys())]
    changed += [f"~ {p}" for p in sorted(pin["files"].keys() & old.keys()) if pin["files"][p] != old[p]]
    print(f"vendored {len(pin['files'])} spec files from launcher {pin['source_commit'][:10]}")
    print("\n".join(changed) if changed else "no spec file changed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path, nargs="?",
                        help="the Launcher's app_function_catalog.json")
    parser.add_argument("--file-tree-spec", type=Path, default=None,
                        help="the Launcher's packages/eternia_file_tree_spec/spec folder")
    parser.add_argument("--launcher", type=Path, default=None,
                        help="the Launcher checkout to stamp (default: the export's directory)")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if (args.export is None) == (args.file_tree_spec is None):
        parser.error("give the catalog export or --file-tree-spec, one of them")
    if args.file_tree_spec is not None:
        return _main_file_tree_spec(args.file_tree_spec, args.launcher, args.out or FILE_TREE_SPEC)
    args.out = args.out or FIXTURE

    raw = json.loads(args.export.read_text(encoding="utf-8-sig"))
    fixture = build_fixture(raw, launcher_head(args.launcher or args.export.resolve().parent))
    old = []
    if args.out.is_file():
        old = json.loads(args.out.read_text(encoding="utf-8-sig")).get("entries", [])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8", newline="\n")
    delta = entry_delta(old, fixture["entries"])
    print(f"vendored {len(fixture['entries'])} entries from launcher {fixture['source_commit'][:10]}")
    print("\n".join(delta) if delta else "no entry changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
