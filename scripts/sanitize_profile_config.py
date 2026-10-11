#!/usr/bin/env python3
"""Cut a sanitized, live-shape copy of profile configs for the test fixtures (D3.05).

A config-reading change is tested against a root shaped like the operator's:
``tests/agent_runtime/test_live_shape_profile_roots.py`` loads these copies
through the snapshot producer. The copy keeps every key and every value's TYPE
and keeps the values the producer branches on — persona ids, toolset and model
names, mode enumerations, booleans, numbers. It never keeps a secret, a path, a
URL, an address or free text (owner ruling D3.05, 2026-10-10: persona/toolset/
model names only, no secrets, no paths):

* a string under a key with a private token (``SENSITIVE_KEY_TOKENS``: ``api_key``,
  ``base_url``, ``workspace_path``, ``voice_id`` …) becomes ``<redacted:<token>>``;
* a string that looks like a path, a URL, an address, an identifier or a
  secret, or is not name-shaped (spaces, over 64 characters), becomes
  ``<redacted:<kind>>``;
* a mapping KEY that is not name-shaped (a path used as a key) becomes
  ``<redacted-key:<kind>-<n>>``.

Comments are dropped (the copy is parsed and re-dumped). Each profile is
written as ``<out>/<profile>/config.yaml`` plus the ``profile.yaml`` identity
marker (``{}``; ``tests/agent_runtime/conftest.py::bundled_persona_profiles``
says why the marker is not ``config.yaml``). Idempotent; re-cut at each release
merge (``Harness_Brain/50 — Agent Handoffs/Merging upstream.md``).

Usage:
    python scripts/sanitize_profile_config.py --root <hermes root> \\
        --out tests/fixtures/profile_roots/live-<yyyy-mm> base neko launcher-qa gpt-launcher
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_runtime import yaml_io  # noqa: E402 — the fork's one YAML door, after the path

#: A key TOKEN (split on punctuation and camelCase) that marks its string value private.
SENSITIVE_KEY_TOKENS = frozenset({
    "key", "keys", "token", "tokens", "secret", "secrets", "password", "passwd", "hash",
    "url", "urls", "uri", "host", "hosts", "path", "paths", "home", "dir", "dirs", "email",
    "user", "username", "client", "project", "account", "voice", "phone",
})
_KEY_SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])")
_NAME_SHAPED = re.compile(r"^[A-Za-z0-9_.:@+/-]{1,64}$")
_DRIVE_OR_HOME = re.compile(r"^[A-Za-z]:[\\/]|^~|^\\\\|^/|[\\/](Users|home)[\\/]", re.IGNORECASE)
_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SECRET_PREFIX = re.compile(r"^(sk-|sk_|pk_|ghp_|gho_|ghs_|github_pat_|xox[abpr]-|AKIA|AIza|eyJ)")
_LONG_RUN = re.compile(r"[A-Za-z0-9]{16,}")
_IDENTIFIER = re.compile(r"^[0-9]{6,}$|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def sensitive_key_token(key: str) -> str | None:
    """The first private-marking token of a mapping key, or None."""

    for token in _KEY_SPLIT.split(key):
        if token.lower() in SENSITIVE_KEY_TOKENS:
            return token.lower()
    return None


def value_kind(text: str) -> str | None:
    """The redaction kind for a string VALUE, or None to keep it."""

    if _URL.search(text):
        return "url"
    if _EMAIL.match(text):
        return "email"
    if _DRIVE_OR_HOME.search(text) or "\\" in text:
        return "path"
    if _IDENTIFIER.match(text):
        return "id"
    if _SECRET_PREFIX.match(text) or _LONG_RUN.search(text):
        return "secret"
    if not _NAME_SHAPED.match(text):
        return "text"
    return None


def sanitize(node, key: str = "", counter: list[int] | None = None):
    counter = counter if counter is not None else [0]
    if isinstance(node, dict):
        out = {}
        for raw_key, value in node.items():
            new_key = raw_key
            if isinstance(raw_key, str):
                kind = value_kind(raw_key)
                if kind is not None:
                    counter[0] += 1
                    new_key = f"<redacted-key:{kind}-{counter[0]}>"
            out[new_key] = sanitize(value, str(raw_key), counter)
        return out
    if isinstance(node, list):
        return [sanitize(item, key, counter) for item in node]
    if isinstance(node, str):
        if node == "":
            return node
        token = sensitive_key_token(key)
        if token is not None:
            return f"<redacted:{token}>"
        kind = value_kind(node)
        return node if kind is None else f"<redacted:{kind}>"
    return node  # bool, int, float, None keep value and type


def cut_profile(root: Path, profile: str, out: Path) -> Path:
    source = root / "profiles" / profile / "config.yaml"
    loaded = yaml_io.load(source.read_text(encoding="utf-8")) or {}
    target_dir = out / profile
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "config.yaml"
    header = f"# Sanitized live-shape copy of profile '{profile}' (scripts/sanitize_profile_config.py).\n"
    target.write_bytes((header + yaml_io.dump(sanitize(loaded))).encode("utf-8"))
    (target_dir / "profile.yaml").write_bytes(b"{}\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, help="the hermes root holding profiles/")
    parser.add_argument("--out", type=Path, required=True, help="fixture directory to write")
    parser.add_argument("profiles", nargs="+")
    args = parser.parse_args(argv)
    for profile in args.profiles:
        print(cut_profile(args.root, profile, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
