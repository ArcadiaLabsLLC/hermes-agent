#!/usr/bin/env python3
"""Bring the running interpreter up to ``requirements-fork-dev.txt``'s pins.

The fork's test-only tools (coverage, pytest-timeout) live in that file and not
in pyproject's ``[dev]``, so ``uv.lock`` stays upstream's. ``scripts/run_tests.sh``
calls this with the venv its probe picked, before any test runs; it is the one
place that installs them. The check reads the file itself, so a pin added
there needs no edit here. pip when the venv has it, else ``uv pip`` (a
``uv sync`` venv has no pip). Exit 0 when satisfied (installed or already
there), 1 when an install was needed and failed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements-fork-dev.txt"


def pins(text: str) -> dict[str, str]:
    """``name==version`` lines → ``{name: version}``; comments and blanks skipped."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, _, pin = line.partition("==")
            out[name.strip()] = pin.strip()
    return out


def unmet(required: dict[str, str]) -> dict[str, str | None]:
    """``{name: installed version or None}`` for every pin the interpreter misses."""
    missing: dict[str, str | None] = {}
    for name, pin in required.items():
        try:
            have = version(name)
        except PackageNotFoundError:
            have = None
        if have != pin:
            missing[name] = have
    return missing


def main(requirements: Path = REQUIREMENTS) -> int:
    if not requirements.is_file():
        return 0
    missing = unmet(pins(requirements.read_text(encoding="utf-8")))
    if not missing:
        return 0
    print(f"> installing fork dev deps {sorted(missing)} from {requirements}", file=sys.stderr)
    probe = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, check=False)
    if probe.returncode == 0:
        command = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(requirements)]
    elif shutil.which("uv"):
        command = ["uv", "pip", "install", "--quiet", "--python", sys.executable, "-r", str(requirements)]
    else:
        print(f"error: {sys.executable} has neither pip nor uv on PATH; install {requirements} by hand", file=sys.stderr)
        return 1
    return 0 if subprocess.run(command, stdout=sys.stderr, check=False).returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
