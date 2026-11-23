"""Record what every plugin registers into ``agent_runtime/plugin_uses.json``.

The snapshot worker loads only the plugins a readied agent uses
(``agent_runtime.plugin_uses``), and it reads that off this record. The record is
taken LIVE: every plugin in this tree and every bundled backend is enabled in a
throwaway Hermes home and loaded with its registrations traced. A plugin that
cannot load here (a missing optional dependency, another OS) is kept from the
committed file rather than dropped, so a record written on one machine never
forgets what another machine saw; the worker admits any plugin the record does
not name.

``--write`` writes; the default prints the record. stdout is the JSON alone.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def all_plugin_keys() -> list[str]:
    from hermes_cli.plugins_discovery import collect_directory_manifests, manifest_key, resolve_manifest_winners

    return sorted(resolve_manifest_winners(collect_directory_manifests()))


def live_record(home: Path) -> dict:
    """Every plugin enabled in ``home`` and recorded (``home`` must be an empty directory)."""

    os.environ["HERMES_HOME"] = str(home)
    keys = all_plugin_keys()
    (home / "config.yaml").write_text(
        json.dumps({"plugins": {"enabled": keys}}), encoding="utf-8"
    )
    from agent_runtime.plugin_uses import record_plugin_uses

    return record_plugin_uses()


def merged(live: dict, committed: dict) -> dict:
    """The committed rows of plugins that did not load here, then this machine's live rows."""

    return {key: committed[key] if key not in live else live[key] for key in sorted({*live, *committed})}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    from agent_runtime.plugin_uses import PLUGIN_USES_PATH, PLUGIN_USES_SCHEMA_VERSION

    try:
        committed = json.loads(PLUGIN_USES_PATH.read_text(encoding="utf-8")).get("plugins") or {}
    except (OSError, ValueError):
        committed = {}
    with tempfile.TemporaryDirectory(prefix="plugin-uses-") as tmp:
        live = live_record(Path(tmp))
    body = json.dumps(
        {"schema_version": PLUGIN_USES_SCHEMA_VERSION, "plugins": merged(live, committed)},
        indent=2, sort_keys=True,
    ) + "\n"
    if args.write:
        PLUGIN_USES_PATH.write_text(body, encoding="utf-8")
        print(f"wrote {PLUGIN_USES_PATH.relative_to(REPO_ROOT)} ({len(live)} live)", file=sys.stderr)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
