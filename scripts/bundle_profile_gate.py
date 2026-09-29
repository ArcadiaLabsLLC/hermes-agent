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
  module level, unguarded: the profile cannot leave it out without a seam;
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


def gate(profile: str) -> dict:
    """Judge ``profile``: the kept modules once, the shipped distributions per target."""
    from agent_runtime.bundle_profiles.manifest import load_profile

    manifest = load_profile(profile)
    unknown = sorted(set(manifest.packaging_targets) - set(TARGETS))
    if unknown:
        raise ValueError(f"packaging.targets names no known target: {unknown}")
    walk, index = profile_walk(manifest, parents=True)
    findings: list[dict] = [{"kind": "pinned", "subject": m, "module": m} for m in sorted(walk.pinned)]
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
            "module_findings": findings, "targets_detail": per_target, "refusals": refused,
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
    lazy = first.get("unguarded_switched_off_imports", [])
    lines += ["", f"Lazy, unguarded imports into switched-off modules (an ImportError if the line runs "
              f"on a phone; each must sit behind its feature's own switch or a seam): {len(lazy)} sites, "
              f"into {len({r['target'] for r in lazy})} modules."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="bundled-phone")
    parser.add_argument("--json", type=Path, help="write the full result here")
    parser.add_argument("--markdown", type=Path, help="write the report table here")
    args = parser.parse_args(argv)
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
