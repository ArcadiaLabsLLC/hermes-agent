"""A seed site that lags ``uv.lock`` is named as the cause (RT-PHONE-BUILD-STALE-SEED-BLAMES-AN-EXTRA).

Seen 2026-11-16 on the Windows box: the default seed (the test venv) held croniter 6.0.0 where
``uv.lock`` pins 6.2.4, so the seed plan followed the old croniter's requirement on pytz, missed
typing-extensions, and the build ended "ship the extra that declares it" — a wrong change.
"""

from __future__ import annotations

import importlib.metadata as md
from pathlib import Path

from tests.scripts.test_bundle_profile_package import _pool_stubs


def _site(root: Path, **versions: str) -> Path:
    for name, version in versions.items():
        info = root / f"{name}-{version}.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8")
    return root


def _lock(path: Path) -> Path:
    path.write_text(
        '[[package]]\nname = "croniter"\nversion = "6.2.4"\n\n'
        '[[package]]\nname = "anyio"\nversion = "4.15.1"\n\n'
        '[[package]]\nname = "numpy"\nversion = "1.26.4"\n\n[[package]]\nname = "numpy"\nversion = "2.1.0"\n\n'
        '[[package]]\nname = "hermes-agent"\nversion = "9.9.9"\nsource = { editable = "." }\n',
        encoding="utf-8")
    return path


def test_a_reached_distribution_off_the_lock_is_named_with_both_versions(tmp_path):
    """Mutations: drop the ``name in wanted`` filter -> the unreached stale anyio is named too, red; read
    one pin per name (``_parsed_lock``'s collapse) -> numpy 1.26.4 reads stale, red."""
    from scripts.bundle_profile_closure import stale_against_lock

    site = _site(tmp_path / "site", croniter="6.0.0", anyio="4.14.2", numpy="1.26.4", hermes_agent="0.1")
    reached = {"croniter", "numpy", "hermes-agent"}
    assert stale_against_lock(md.distributions(path=[str(site)]), reached, _lock(tmp_path / "uv.lock")) == [
        "croniter 6.0.0 (uv.lock 6.2.4)"]


def test_a_build_over_a_stale_seed_stops_before_the_pool_naming_it(monkeypatch, capsys, tmp_path):
    """The real ``uv.lock`` pins croniter 6.2.4; a seed holding 6.0.0 that the seed plan reaches ends the
    build before anything is installed, and the receipt names the seed, not an extra.
    Mutation: drop the ``return 1`` after the stale receipt -> the pool installs, red."""
    pkg, args, manifest, _calls, installed = _pool_stubs(
        monkeypatch, tmp_path, "CLOSURE", {"": {"croniter"}, "pk": {"croniter"}})
    _site(args.seed_sites[0], croniter="6.0.0")

    assert pkg._build(args, manifest, {}, tmp_path / "core.pool", None) == 1

    out = capsys.readouterr().out
    assert installed == []
    assert "the seed site lags uv.lock: croniter 6.0.0 (uv.lock " in out
    assert "ship the extra" not in out
