"""Harness config keys live under ``plugins.entries.eternia-harness.settings``.

One reader (``agent_runtime.harness_settings``), declared in the plugin
manifest's ``config_schema``, with the legacy top-level ``remote_gateway.*`` /
``charsheet.*`` keys still read — and losing — during the stated transition.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_runtime import harness_settings
from agent_runtime.gateway_endpoints.candidates import gateway_listen_config

ROOT = Path(__file__).resolve().parents[2]


def _settings(**values):
    return {"plugins": {"entries": {"eternia-harness": {"settings": dict(values)}}}}


@pytest.fixture
def config(monkeypatch):
    import hermes_cli.config as config_module

    def _install(cfg):
        monkeypatch.setattr(config_module, "load_config_readonly", lambda: cfg)

    return _install


def test_the_gateway_listener_reads_the_plugin_settings_path(config):
    config(_settings(remote_gateway_listen="0.0.0.0", remote_gateway_port=8765))
    assert gateway_listen_config() == ("0.0.0.0", 8765)


def test_the_new_path_wins_over_a_legacy_key_left_behind(config):
    cfg = _settings(remote_gateway_listen=False)
    cfg["remote_gateway"] = {"listen": "0.0.0.0", "port": 8765}
    config(cfg)
    assert gateway_listen_config() == (None, 0)


def test_a_legacy_only_config_is_still_read_during_the_transition(config):
    config({"remote_gateway": {"listen": "192.168.1.40", "port": 9000}})
    assert gateway_listen_config() == ("192.168.1.40", 9000)


def test_the_charsheet_deadline_reads_the_plugin_settings_path(config):
    from agent.charsheet import pipeline

    config(_settings(charsheet_provider_timeout_seconds=42))
    assert pipeline.provider_timeout_seconds() == 42.0


def test_every_harness_setting_is_declared_in_the_plugin_manifest():
    from hermes_cli.plugins_manifest import parse_manifest_file

    plugin_dir = ROOT / "plugins" / "eternia-harness"
    manifest = parse_manifest_file(plugin_dir / "plugin.yaml", plugin_dir, "bundled", "")
    assert manifest is not None
    declared = set(manifest.config_schema)
    assert set(harness_settings.LEGACY_KEYS) <= declared, set(harness_settings.LEGACY_KEYS) - declared


_LEGACY_READ = re.compile(
    r"""(?:\.get\(\s*|cfg_get\(.*?,\s*|\[\s*)["'](?:remote_gateway|charsheet)["']"""
)


def test_no_fork_module_reads_a_legacy_block_but_the_one_reader():
    """NEGATIVE, so a source walk is the right tool: nothing outside
    ``harness_settings.py`` may read the legacy top-level blocks."""
    roots = [ROOT / "agent_runtime", ROOT / "hermes_cli" / "harness_parts", ROOT / "agent" / "charsheet",
             ROOT / "plugins" / "eternia-harness"]
    offenders = []
    for root in roots:
        for path in root.rglob("*.py"):
            if path.name == "harness_settings.py":
                continue
            text = path.read_text(encoding="utf-8")
            offenders += [f"{path.relative_to(ROOT)}: {m.group(0)}" for m in _LEGACY_READ.finditer(text)]
    assert offenders == []


def test_the_walk_sees_a_legacy_read_when_one_is_planted():
    """Positive control for the walk above."""
    assert _LEGACY_READ.search('block = load_config_readonly().get("remote_gateway") or {}')
    assert _LEGACY_READ.search('cfg_get(load_config_readonly(), "charsheet", key, default=default)')
