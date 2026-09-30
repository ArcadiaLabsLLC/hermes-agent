"""Profile gate: may a bundle profile ship to its targets? — over the whole-wheel import closure.

Replaces the July ``mobile_core/tools/import_gate.py``, which scanned one
vendored package and banned the ``agent_runtime`` / config / auth code phones
now import from the real wheel (architecture §4, "Profile gate"). This gate
reads the profile manifest and walks what the profile PACKAGES — its roots, its
bundled plugins, the enclosing packages of every kept module (their
``__init__`` runs on import), never into ``packaging.switched_off_modules`` —
with the closure walk of ``scripts/bundle_profile_closure.py`` (one walk, one
set of shipping rules; this module only judges the result).

Refused (each a row with the evidence that convicts it):

* ``provider_sdk`` — a provider SDK ships (architecture §6: raw HTTP only);
* ``native`` — a compiled distribution ships (no pure-Python wheel in
  ``uv.lock`` — Rust-backed ``pydantic-core`` / ``jiter`` are the headline
  cases) and ``packaging.admitted_native`` does not admit it;
* ``unproven`` — a shipped distribution has no wheel in ``uv.lock`` to judge;
* ``process`` — ``psutil`` / pty packages ship, or a kept module imports the
  stdlib ``pty`` / ``tty`` / ``termios`` outside an ImportError guard;
* ``browser`` — a browser or computer-use tool module is kept, or a browser
  automation distribution ships;
* ``subprocess_call`` — a kept module CALLS a process spawner (the stdlib
  import alone is allowed: the auth path reaches it);
* ``pinned`` — a switched-off (absent) module that a kept module imports at
  module level, unguarded: the profile cannot leave it out without a seam. The
  loop's lifecycle placeholders are such a seam: a module whose every imported
  name resolves on the placeholder the embedded entry registers — asked in a
  child interpreter with the switched-off modules absent — is reported as
  answered, not pinned;
* ``closure`` — the closure's own packaging refusals (an omitted distribution
  imported unguarded, …).

Pure-Python dependencies (``requests``, ``httpx``, …) are allowed. A profile
that names no ``packaging.targets`` is judged for the desktop interpreter.

The refusal list is the work list, not an embarrassment: ``--markdown`` writes
it for the doc the Stage 2 row points at, and the exit code is 1 while it is
non-empty.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.bundle_profile_closure import (  # noqa: E402 — after the path insert, like the closure's own callers
    TARGETS,
    _guarded_ids,
    _lock,
    _norm,
    closure,
    profile_walk,
    refusals as closure_refusals,
)

#: Provider SDKs: architecture §6 — phones call every provider over raw HTTP.
PROVIDER_SDKS = frozenset({
    "openai", "anthropic", "elevenlabs", "mcp", "google-genai", "google-generativeai",
    "google-cloud-aiplatform", "mistralai", "cohere", "groq", "boto3", "botocore",
    "azure-identity", "litellm", "fal-client", "together", "replicate",
})
#: Process-table / pseudo-terminal distributions.
PROCESS_DISTRIBUTIONS = frozenset({"psutil", "ptyprocess", "pexpect", "pywinpty"})
#: Stdlib pseudo-terminal modules (a phone has no terminal to allocate).
PTY_MODULES = frozenset({"pty", "tty", "termios"})
#: Browser automation distributions.
BROWSER_DISTRIBUTIONS = frozenset({"playwright", "selenium", "browser-use", "pyppeteer"})
#: First-party browser / computer-use tool modules (prefixes).
BROWSER_MODULE_PREFIXES = ("tools.browser", "tools.computer_use", "plugins.browser")
#: Process spawners, by dotted call name. ``subprocess`` itself may be imported.
SPAWN_CALLS = frozenset({
    *(f"subprocess.{n}" for n in ("run", "Popen", "call", "check_call", "check_output",
                                   "getoutput", "getstatusoutput")),
    *(f"os.{n}" for n in ("system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp",
                           "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve",
                           "spawnvp", "spawnvpe", "execl", "execle", "execlp", "execlpe",
                           "execv", "execve", "execvp", "execvpe", "startfile")),
    "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell",
})


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr}" if head else None
    return None


def _parse(path: Path) -> ast.AST | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


def module_findings(module: str, path: Path) -> list[dict]:
    """Spawn calls and unguarded pty imports in one kept module's source."""
    tree = _parse(path)
    if tree is None:
        return []
    guarded = _guarded_ids(tree)
    # Local names bound to a spawner or its module: ``from subprocess import run as r``,
    # ``import subprocess as sp``.
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("subprocess", "os", "asyncio"):
                    aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module in ("subprocess", "os", "asyncio") \
                and not node.level:
            for alias in node.names:
                if f"{node.module}.{alias.name}" in SPAWN_CALLS:
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name is None:
                continue
            head, _, rest = name.partition(".")
            resolved = aliases.get(name) or (f"{aliases[head]}.{rest}" if rest and head in aliases else None)
            if resolved in SPAWN_CALLS:
                found.append({"kind": "subprocess_call", "subject": resolved, "module": module,
                              "line": node.lineno})
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and id(node) not in guarded:
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if not node.level else []
            for name in names:
                if name.split(".")[0] in PTY_MODULES:
                    found.append({"kind": "process", "subject": name.split(".")[0], "module": module,
                                  "line": node.lineno})
    return found


def is_pure(lock_entry: dict) -> bool | None:
    """True: a pure-Python wheel exists; False: only compiled wheels; None: no wheel to judge."""
    wheels = [w.get("url", "") for w in lock_entry.get("wheels", [])]
    if not wheels:
        return None
    return any(url.endswith("-none-any.whl") for url in wheels)


def distribution_findings(shipped, lock: dict[str, dict], admitted_native) -> list[dict]:
    admitted = {_norm(d) for d in admitted_native}
    out = []
    for name in sorted(shipped):
        if name in PROVIDER_SDKS:
            out.append({"kind": "provider_sdk", "subject": name})
        if name in PROCESS_DISTRIBUTIONS:
            out.append({"kind": "process", "subject": name})
        if name in BROWSER_DISTRIBUTIONS:
            out.append({"kind": "browser", "subject": name})
        entry = lock.get(name)
        if entry is None:
            out.append({"kind": "unproven", "subject": name, "detail": "not in uv.lock"})
            continue
        pure = is_pure(entry)
        if pure is None:
            out.append({"kind": "unproven", "subject": name, "detail": "no wheel in uv.lock"})
        elif not pure and name not in admitted:
            out.append({"kind": "native", "subject": name})
    return out


def _import_from_base(node: ast.ImportFrom, package: str) -> str:
    """The absolute module an ``ImportFrom`` names, a relative one resolved against ``package``."""
    base = node.module or ""
    if not node.level:
        return base
    anchor = package.split(".")[: len(package.split(".")) - (node.level - 1)]
    return ".".join([*anchor, base] if base else anchor)


def _record_eager_imports(tree: ast.Module, package: str, out: dict[str, set[str] | None]) -> None:
    """Fold one kept module's unguarded module-level imports of pinned modules into ``out``."""
    guarded = _guarded_ids(tree)
    for node in tree.body:
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in out:
                    out[alias.name] = None
        elif isinstance(node, ast.ImportFrom):
            base = _import_from_base(node, package)
            if base in out and out[base] is not None:
                out[base].update(alias.name for alias in node.names)


def eager_imported_names(pinned: set[str], kept, index: dict[str, Path]) -> dict[str, set[str] | None]:
    """pinned module -> the names kept modules import from it at module level, unguarded; None
    when some kept module binds the module itself (``import m``), whose later uses no name list
    can bound."""
    out: dict[str, set[str] | None] = {m: set() for m in pinned}
    for module in kept:
        path = index[module]
        tree = _parse(path)
        if tree is None:
            continue
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        _record_eager_imports(tree, package, out)
    return out


#: Run in a child interpreter: the profile's switched-off modules absent, the loop's placeholders
#: registered as the embedded entry registers them, then each name the kept code imports at module
#: level asked of the module that is actually in ``sys.modules``.
_PLACEHOLDER_PROBE = r"""
import json, sys
root, off, wanted = sys.argv[1], tuple(json.loads(sys.argv[2])), json.loads(sys.argv[3])
sys.path.insert(0, root)

class Absent:
    def find_spec(self, name, path=None, target=None):
        if any(name == m or name.startswith(m + ".") for m in off):
            raise ModuleNotFoundError(f"switched off: {name}", name=name)

sys.meta_path.insert(0, Absent())
from agent_runtime.loop_tool_lifecycles import ensure_lifecycle_placeholders, is_lifecycle_placeholder

ensure_lifecycle_placeholders()
answered = {}
for module, names in wanted.items():
    stand_in = sys.modules.get(module)
    ok = stand_in is not None and is_lifecycle_placeholder(stand_in)
    for name in names:
        try:
            getattr(stand_in, name)  # a table name resolves (a stand-in callable or value); any other raises
        except Exception:
            ok = False
    answered[module] = ok
print(json.dumps(answered))
"""


def placeholder_seams(manifest, walk, index: dict[str, Path]) -> dict[str, list[str]]:
    """The pinned modules the loop's placeholders (``agent_runtime.loop_tool_lifecycles``) answer:
    every name kept code imports from them at module level resolves on the placeholder the embedded
    entry registers. Proven at run time in a child interpreter, never by reading the placeholder
    table's spelling: a name the table lacks raises there, and the module stays pinned."""
    import subprocess

    names = eager_imported_names(set(walk.pinned), walk.kept, index)
    wanted = {m: sorted(n) for m, n in names.items() if n}
    if not wanted:
        return {}
    done = subprocess.run(
        [sys.executable, "-c", _PLACEHOLDER_PROBE, str(ROOT), json.dumps(list(manifest.switched_off_modules)),
         json.dumps(wanted)],
        capture_output=True, text=True, timeout=300, cwd=ROOT)
    if done.returncode != 0:
        raise RuntimeError(f"placeholder probe failed: {done.stderr[-2000:]}")
    answered = json.loads(done.stdout.strip().splitlines()[-1])
    return {m: wanted[m] for m in sorted(wanted) if answered.get(m)}


def gate(profile: str) -> dict:
    """Judge ``profile``: the kept modules once, the shipped distributions per target."""
    from agent_runtime.bundle_profiles.manifest import load_profile

    manifest = load_profile(profile)
    unknown = sorted(set(manifest.packaging_targets) - set(TARGETS))
    if unknown:
        raise ValueError(f"packaging.targets names no known target: {unknown}")
    walk, index = profile_walk(manifest, parents=True)
    seams = placeholder_seams(manifest, walk, index)
    findings: list[dict] = [{"kind": "pinned", "subject": m, "module": m}
                            for m in sorted(walk.pinned) if m not in seams]
    for module in sorted(walk.kept):
        if module.startswith(BROWSER_MODULE_PREFIXES):
            findings.append({"kind": "browser", "subject": module, "module": module})
        findings += module_findings(module, index[module])
    lock = _lock()
    targets = manifest.packaging_targets or (None,)
    per_target = {}
    for target in targets:
        result = closure(profile, boot=False, target=target, parents=True)
        shipped = {row["name"] for row in result["needed"]}
        per_target[target or "win_amd64"] = {
            "shipped": sorted(shipped),
            "findings": distribution_findings(shipped, lock, manifest.admitted_native)
            + [{"kind": "closure", "subject": reason} for reason in closure_refusals(result)],
            "reached_via": result["reached_via"],
            "pinned_switched_off_modules": result["pinned_switched_off_modules"],
            "unguarded_switched_off_imports": result["unguarded_switched_off_imports"],
        }
    refused = findings + [dict(f, target=t) for t, row in per_target.items() for f in row["findings"]]
    return {"profile": manifest.profile, "targets": list(per_target), "kept_modules": len(walk.kept),
            "placeholder_seams": seams, "module_findings": findings, "targets_detail": per_target, "refusals": refused,
            "passed": not refused}


def summary(result: dict) -> dict[str, list[str]]:
    """kind -> sorted distinct subjects (a subject refused on every target is listed once)."""
    out: dict[str, set[str]] = {}
    for row in result["refusals"]:
        out.setdefault(row["kind"], set()).add(row["subject"])
    return {kind: sorted(subjects) for kind, subjects in sorted(out.items())}


def render_markdown(result: dict) -> str:
    rows = summary(result)
    lines = [f"Profile `{result['profile']}`, targets {', '.join(result['targets'])}; "
             f"{result['kept_modules']} first-party modules kept. "
             f"Verdict: **{'PASS' if result['passed'] else 'REFUSED'}** "
             f"({len(result['refusals'])} findings).", "",
             "| kind | distinct subjects | subjects |", "|---|---:|---|"]
    for kind, subjects in rows.items():
        if kind == "subprocess_call":
            modules = sorted({r["module"] for r in result["module_findings"] if r["kind"] == kind})
            lines.append(f"| {kind} | {len(modules)} modules | "
                         f"{', '.join(f'`{m}`' for m in modules)} |")
        else:
            lines.append(f"| {kind} | {len(subjects)} | {', '.join(f'`{s}`' for s in subjects)} |")
    lines += ["", "How each shipped distribution is first reached (first target):", "",
              "| distribution | via |", "|---|---|"]
    first = next(iter(result["targets_detail"].values()), {})
    flagged = {r["subject"] for r in result["refusals"]}
    for dist, via in sorted(first.get("reached_via", {}).items()):
        if dist in flagged:
            lines.append(f"| {dist} | `{' → '.join(via)}` |")
    seams = result.get("placeholder_seams") or {}
    if seams:
        lines += ["", "Switched-off modules kept code imports at module level that the loop's placeholders "
                  "(`agent_runtime/loop_tool_lifecycles.py`) answer — proven at run time, not pinned: "
                  + "; ".join(f"`{m}` ({', '.join(f'`{n}`' for n in names)})" for m, names in seams.items()) + "."]
    lazy = first.get("unguarded_switched_off_imports", [])
    lines += ["", f"Lazy, unguarded imports into switched-off modules (an ImportError if the line runs "
              f"on a phone; each must sit behind its feature's own switch or a seam): {len(lazy)} sites, "
              f"into {len({r['target'] for r in lazy})} modules."]
    return "\n".join(lines) + "\n"


#: The CPython the bundle ships (PM's pin, copied for the installer). The gate's count depends on the
#: interpreter it runs under — the AST it parses with, the stdlib it resolves, the child probes it
#: spawns — so one run is comparable with another only under the same one: this one's major.minor.
INTERPRETER_LOCK = ROOT / "agent_runtime" / "bundle_profiles" / "interpreters.lock.json"


def pinned_interpreter() -> tuple[str, tuple[int, int]]:
    """``(full pin, (major, minor))`` from :data:`INTERPRETER_LOCK`, e.g. ``("3.14.7+20260901", (3, 14))``."""
    version = json.loads(INTERPRETER_LOCK.read_text(encoding="utf-8"))["version"]
    major, minor = version.split("+")[0].split(".")[:2]
    return version, (int(major), int(minor))


def _same_file(a: str | Path, b: str | Path) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve() or Path(a).samefile(b)
    except OSError:
        return False


def interpreter_refusal(explicit: str | None, *, executable: str | None = None,
                        implementation: str | None = None, version: tuple[int, int] | None = None) -> str | None:
    """Why the gate must not run under this interpreter, or ``None``: it runs under the bundle's pinned
    CPython (major.minor of :data:`INTERPRETER_LOCK`), or under the interpreter ``--interpreter`` names."""
    executable = executable or sys.executable
    implementation = implementation or sys.implementation.name
    version = version or tuple(sys.version_info[:2])
    if explicit is not None:
        if _same_file(explicit, executable):
            return None
        return f"--interpreter names {explicit}, but the gate is running under {executable}"
    pin, want = pinned_interpreter()
    if implementation == "cpython" and version == want:
        return None
    return (f"the gate runs under the bundle's pinned CPython {want[0]}.{want[1]} ({pin}, "
            f"{INTERPRETER_LOCK.relative_to(ROOT).as_posix()}) so counts compare like with like; this is "
            f"{implementation} {version[0]}.{version[1]} at {executable}. Run it with a {want[0]}.{want[1]} "
            f"interpreter that has the dev dependencies, or name this one with --interpreter to override")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="bundled-phone")
    parser.add_argument("--json", type=Path, help="write the full result here")
    parser.add_argument("--markdown", type=Path, help="write the report table here")
    parser.add_argument("--interpreter", help="run under this interpreter although it is not the pinned CPython "
                        "(it must be the one running the gate; the count is then not comparable with pinned runs)")
    args = parser.parse_args(argv)
    print(f"interpreter: {sys.executable} ({sys.implementation.name} {sys.version.split()[0]})"
          + (" — explicit --interpreter override" if args.interpreter else ""), flush=True)
    refusal = interpreter_refusal(args.interpreter)
    if refusal:
        print(f"GATE NOT RUN: {refusal}", file=sys.stderr)
        return 2
    result = gate(args.profile)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8", newline="")
    if args.markdown:
        args.markdown.write_text(render_markdown(result), encoding="utf-8", newline="")
    for kind, subjects in summary(result).items():
        print(f"REFUSED {kind}: {len(subjects)} — {', '.join(subjects[:12])}{' …' if len(subjects) > 12 else ''}")
    print("PASS" if result["passed"] else f"REFUSED ({len(result['refusals'])} findings)")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
