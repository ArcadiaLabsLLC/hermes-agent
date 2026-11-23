"""The bundle's runtime probes: the named timezone resolves and the profile's serve entry imports.

Split out of ``scripts/bundle_profile_package.py`` (W0-G1 size ceiling); the packager's
``verify_bundle`` runs both against a built bundle with the bundle's own interpreter.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

from agent_runtime.bundle_profiles.forced_tree import FORCED_TREE_DIR
from scripts.bundle_profile_closure import _imports, _owner


#: A named zone the bundle must resolve. Windows has no system timezone database, so stdlib
#: ``zoneinfo`` reads the ``tzdata`` distribution (``hermes_time``, cron's named timezones).
NAMED_TIMEZONE = "America/New_York"
_TIMEZONE_PROBE = (
    "import sys, zoneinfo; sys.path.insert(0, sys.argv[1]); zoneinfo.reset_tzpath(()); "
    "zoneinfo.ZoneInfo(sys.argv[2])")


def named_timezone_problems(site: Path, python: Path | str = sys.executable) -> list[str]:
    """``zoneinfo`` resolves :data:`NAMED_TIMEZONE` from ``site`` alone (``-I -S``, no TZPATH)."""
    done = subprocess.run([str(python), "-I", "-S", "-B", "-c", _TIMEZONE_PROBE, str(site), NAMED_TIMEZONE],
                          capture_output=True, text=True, timeout=120, check=False)
    if done.returncode == 0:
        return []
    last = (done.stderr.strip().splitlines() or ["(no output)"])[-1]
    return [f"named timezone {NAMED_TIMEZONE} does not resolve inside the bundle: {last}"]


#: The argv bundled Hermes starts with (``python -I -m hermes_cli.main harness serve --ndjson``,
#: the manifest's serve entry). The probe resolves its handler from the bundle's OWN parser.
SERVE_ARGV = ("harness", "serve", "--ndjson")

#: A profile's entry (the first of its ``packaging.roots``) -> the argv it is started with, for an
#: entry that is a command line: the desktop's ``hermes_cli.main``, whose serve handler only its
#: parser names. Any other entry (the phone's embedded serve, ``hermes_cli.harness_parts.serve.
#: in_memory``, which ships no CLI parser) is a module its host imports, and the probe imports it.
COMMAND_LINE_ENTRIES: dict[str, tuple[str, ...]] = {"hermes_cli.main": SERVE_ARGV}

#: What an embedded entry runs in its process before it serves (the stand-ins, the contract catalog,
#: the chat-turn parser: ``hermes_cli.harness_parts.serve.in_memory``'s host contract); the probe calls
#: it after importing the entry, so the walk sees the process the phone serves from.
EMBEDDED_PREPARE = "prepare_embedded_process"

_SERVE_IMPORT_PROBE = r"""
import argparse, importlib, json, sys
# The report's own channel, saved before any import: a module may swap ``sys.stdout`` at import
# (``tui_gateway.server`` points it at stderr), and the parent reads only this process's stdout.
report = sys.stdout
app, site, table_path, root_entry, argv, tree = (sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4],
                                                 json.loads(sys.argv[5]), sys.argv[6])
target = json.loads(sys.argv[7])
# A bundle for another platform (a phone's, probed on this host): its compiled wheels cannot load here.
cross = bool(target["platform"]) and target["platform"] != sys.platform
native_tops, skipped = set(target["native_tops"]), []
switched_off, not_run = tuple(target["switched_off"]), []
sys.path[:0] = [app, site]
if tree:  # the sibling tree, mounted as the embedded entry mounts it (forced_tree.mount_forced_tree)
    import os
    for package in ("tools", "plugins"):
        if os.path.isdir(os.path.join(tree, package)):
            importlib.import_module(package).__path__.append(os.path.join(tree, package))
with open(table_path, encoding="utf-8") as handle:
    table = json.load(handle)
lazy, spawned, packages_known = table["lazy"], table["spawned"], set(table["packages"])
failures, tried = [], []
def load(name):
    if name in tried:
        return
    tried.append(name)
    if any(name == off or name.startswith(off + ".") for off in switched_off):
        not_run.append(name)  # the profile switches it off: it ships only as code kept code names (the gate's)
        return
    try:
        importlib.import_module(name)
    except ImportError as exc:  # a compiled wheel built for the target, not this host: said, not failed
        if cross and (exc.name or "").split(".")[0] in native_tops:
            skipped.append(f"{name}: {type(exc).__name__}: {exc}")
        else:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    except BaseException as exc:
        failures.append(f"{name}: {type(exc).__name__}: {exc}")
if argv:  # a command-line entry: its serve handler, as the bundle's OWN parser resolves the argv
    from hermes_cli.harness_parts.parser import build_parser
    root = argparse.ArgumentParser(prog="hermes")
    build_parser(root.add_subparsers(dest="command"))
    entry = root.parse_args(argv).func.__module__
else:  # an embedded entry: the module the host app imports, in the process it prepares
    entry = root_entry
    if cross and target["phone"]:  # the install is the phone's (its profile's switches), as on the phone
        from agent_runtime import installed_profile
        installed_profile.PHONE_PLATFORMS = installed_profile.PHONE_PLATFORMS | {sys.platform}
load(entry)
if not argv and entry in sys.modules:
    try:
        getattr(sys.modules[entry], target["prepare"])()
    except BaseException as exc:
        failures.append(f"{entry}.{target['prepare']}(): {type(exc).__name__}: {exc}")
# The handler's own lazy imports (the serve command module; for the embedded entry, what its
# ``start`` binds: the chat-turn parser, the stand-ins), then every lazy import of the
# modules loaded under those packages (the serve loop's runtime.* lane, ...).
first = lazy.get(entry, [])
for name in first:
    load(name)
packages = {n if n in packages_known else n.rpartition(".")[0] for n in first} - {""}
for module in sorted(m for m in list(sys.modules) if any(m.startswith(p + ".") for p in packages)):
    for name in lazy.get(module, []):
        load(name)
for name in spawned:  # the ``python -m <module>`` children a shipped module starts
    load(name)
print(json.dumps({"entry": entry, "tried": tried, "failures": failures, "skipped": skipped,
                  "switched_off": not_run}), file=report,
      flush=True)
"""


def _spawned_modules(path: Path) -> list[str]:
    """``"-m", "<literal>"`` adjacent in a list/tuple literal: a ``python -m`` child process."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            for flag, name in zip(node.elts, node.elts[1:]):
                if (isinstance(flag, ast.Constant) and flag.value == "-m" and isinstance(name, ast.Constant)
                        and isinstance(name.value, str)):
                    found.append(name.value)
    return found


def serve_import_table(modules: set[str], index: dict[str, Path]) -> dict:
    """What the probe imports, read from the code: each shipped module's lazy unguarded
    first-party imports, and every ``-m <module>`` a shipped module spawns."""
    lazy: dict[str, list[str]] = {}
    spawned: set[str] = set()
    for module in sorted(modules):
        path = index.get(module)
        if path is None:
            continue
        targets: list[str] = []
        for dotted, eager, guarded, _line in _imports(path, module, path.name == "__init__.py"):
            owner = _owner(dotted, index)
            if not eager and not guarded and owner in modules and owner != module and owner not in targets:
                targets.append(owner)
        if targets:
            lazy[module] = targets
        spawned.update(m for m in _spawned_modules(path) if m in modules)
    packages = sorted(m for m in modules if index.get(m) is not None and index[m].name == "__init__.py")
    return {"lazy": lazy, "spawned": sorted(spawned), "packages": packages}


def serve_import_problems(out: Path, first_party: set[str], index: dict[str, Path], python_version: str,
                          python: Path | str = sys.executable, *, roots: tuple[str, ...],
                          target_platform: str = "", phone: bool = False,
                          native_tops: tuple[str, ...] = (), switched_off: tuple[str, ...] = ()) -> list[str]:
    """The bundle's interpreter, isolated (``-I -S -B``, only ``app`` + ``site-packages``), imports
    what the profile's serve loads: its entry (``roots[0]``, the profile's ``packaging.roots``; a
    command-line entry's handler from the bundle's own parser), the entry's lazy imports and theirs,
    and the ``-m`` children a shipped module spawns (conversation workers).

    ``target_platform`` is the bundle's ``sys.platform``. When ``python`` runs on another one (a phone
    bundle probed on this host), an import that fails inside ``native_tops`` (the import names of the
    profile's ``packaging.admitted_native`` wheels, compiled for the target) is printed as skipped,
    by module, never failed; and for a ``phone`` bundle the install is made the phone's. A module under
    ``switched_off`` (the profile's ``packaging.switched_off_modules``) is not imported: it does not run
    under the profile, and the profile gate judges the edges into it; one line names those passed by."""
    entry = roots[0]
    done = subprocess.run([str(python), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                          capture_output=True, text=True, timeout=60, check=False)
    have, want = done.stdout.strip(), ".".join(python_version.split(".")[:2])
    if have != want:
        return [f"serve import probe needs a CPython {want} interpreter (--python); {python} is {have or '?'}"]
    with tempfile.TemporaryDirectory(prefix="hermes-serve-probe-") as scratch:
        table = Path(scratch) / "table.json"
        table.write_text(json.dumps(serve_import_table(first_party, index)), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HERMES", "PYTHON"))}
        env["HERMES_HOME"] = str(Path(scratch) / "home")
        done = subprocess.run([str(python), "-I", "-S", "-B", "-c", _SERVE_IMPORT_PROBE, str(out / "app"),
                               str(out / "site-packages"), str(table), entry,
                               json.dumps(list(COMMAND_LINE_ENTRIES.get(entry, ()))),
                               str(out / FORCED_TREE_DIR) if (out / FORCED_TREE_DIR).is_dir() else "",
                               json.dumps({"platform": target_platform, "phone": phone, "prepare": EMBEDDED_PREPARE,
                                           "native_tops": sorted(native_tops), "switched_off": list(switched_off)})],
                              capture_output=True, text=True, timeout=300, env=env, cwd=scratch,
                              stdin=subprocess.DEVNULL, check=False)
    lines = done.stdout.strip().splitlines()
    if done.returncode != 0 or not lines:
        last = (done.stderr.strip().splitlines() or ["(no output)"])[-1]
        return [f"serve import probe did not run: {last}"]
    result = json.loads(lines[-1])
    if result["switched_off"]:
        print(f"serve import probe: not imported, switched off by the profile: {', '.join(result['switched_off'])}",
              flush=True)
    for line in result["skipped"]:
        print(f"serve import probe: skipped, compiled for {target_platform}, not this host: {line}", flush=True)
    return [f"serve entrypoint does not import inside the bundle: {line}" for line in result["failures"]]
