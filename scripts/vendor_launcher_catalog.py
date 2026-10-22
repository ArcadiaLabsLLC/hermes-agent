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
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "launcher_app_functions_catalog.json"

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path, help="the Launcher's app_function_catalog.json")
    parser.add_argument("--launcher", type=Path, default=None,
                        help="the Launcher checkout to stamp (default: the export's directory)")
    parser.add_argument("--out", type=Path, default=FIXTURE)
    args = parser.parse_args(argv)

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
