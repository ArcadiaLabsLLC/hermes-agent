"""Fork-owned tests moved out of ``tests/hermes_cli/test_mcp_config.py`` (lane CARRY2A).

Same names, same bodies; the upstream file is byte-identical to upstream. The
upstream autouse ``_isolate_config`` is imported by name so it applies here too.
"""

from typing import Any, Dict

from tests.hermes_cli.test_mcp_config import (  # noqa: F401 — upstream fixture + helpers
    _isolate_config,
    _make_args,
    _seed_config,
)



class TestMcpTestRuntimeEnv:
    """One-shot ``--env KEY=VALUE`` overrides for ``hermes mcp test``."""

    def _seed_stdio_server(self, tmp_path):
        _seed_config(tmp_path, {
            "foo": {"command": "/bin/true", "env": {"FOO_BASE": "base"}},
        })

    def test_runtime_env_passes_to_probe(self, tmp_path, monkeypatch):
        self._seed_stdio_server(tmp_path)
        captured: Dict[str, Any] = {}

        def mock_probe(name, config, **kw):
            captured["config"] = config
            return []

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe
        )
        from hermes_cli.mcp_config import cmd_mcp_test

        cmd_mcp_test(_make_args(name="foo", env=["RUNTIME_FILE=/tmp/r"]))

        assert captured["config"]["runtime_env"] == {"RUNTIME_FILE": "/tmp/r"}
        # Durable env stays alongside, NOT replaced.
        assert captured["config"]["env"] == {"FOO_BASE": "base"}

    def test_runtime_env_does_not_persist(self, tmp_path, monkeypatch):
        self._seed_stdio_server(tmp_path)
        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server",
            lambda name, config, **kw: [],
        )
        from hermes_cli.mcp_config import cmd_mcp_test

        cmd_mcp_test(_make_args(name="foo", env=["SECRET_KEY=topsecret"]))

        from hermes_cli.config import load_config
        saved = load_config()
        # The on-disk config must not gain runtime_env or the secret key.
        srv = saved["mcp_servers"]["foo"]
        assert "runtime_env" not in srv
        assert "SECRET_KEY" not in srv.get("env", {})

    def test_runtime_env_invalid_kv_aborts(self, tmp_path, capsys, monkeypatch):
        self._seed_stdio_server(tmp_path)
        probe_called = {"hit": False}

        def mock_probe(*a, **kw):
            probe_called["hit"] = True
            return []

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe
        )
        from hermes_cli.mcp_config import cmd_mcp_test

        cmd_mcp_test(_make_args(name="foo", env=["NO_EQUALS_HERE"]))
        out = capsys.readouterr().out
        assert "Invalid --env value" in out
        assert probe_called["hit"] is False

    def test_runtime_env_invalid_name_aborts(self, tmp_path, capsys,
                                              monkeypatch):
        self._seed_stdio_server(tmp_path)
        probe_called = {"hit": False}
        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server",
            lambda *a, **kw: probe_called.__setitem__("hit", True) or [],
        )
        from hermes_cli.mcp_config import cmd_mcp_test

        cmd_mcp_test(_make_args(name="foo", env=["1BAD=value"]))
        out = capsys.readouterr().out
        assert "Invalid --env variable name" in out
        assert probe_called["hit"] is False

    def test_runtime_env_rejected_for_http(self, tmp_path, capsys, monkeypatch):
        _seed_config(tmp_path, {
            "ink": {"url": "https://mcp.example/mcp"},
        })
        probe_called = {"hit": False}
        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server",
            lambda *a, **kw: probe_called.__setitem__("hit", True) or [],
        )
        from hermes_cli.mcp_config import cmd_mcp_test

        cmd_mcp_test(_make_args(name="ink", env=["DEBUG=true"]))
        out = capsys.readouterr().out
        assert "only supported for stdio MCP servers" in out
        assert probe_called["hit"] is False

    def test_runtime_env_value_never_printed(self, tmp_path, capsys,
                                              monkeypatch):
        self._seed_stdio_server(tmp_path)
        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server",
            lambda name, config, **kw: [],
        )
        from hermes_cli.mcp_config import cmd_mcp_test

        cmd_mcp_test(
            _make_args(name="foo", env=["TOKEN=super-secret-value"])
        )
        captured = capsys.readouterr()
        assert "super-secret-value" not in captured.out
        assert "super-secret-value" not in captured.err
        # The key name is fine to show.
        assert "TOKEN" in captured.out
        assert "Applied 1 one-shot env override" in captured.out

    def test_no_env_arg_is_backward_compatible(self, tmp_path, monkeypatch):
        """Existing call sites that don't pass --env behave identically."""
        self._seed_stdio_server(tmp_path)
        captured: Dict[str, Any] = {}

        def mock_probe(name, config, **kw):
            captured["config"] = config
            return []

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe
        )
        from hermes_cli.mcp_config import cmd_mcp_test

        cmd_mcp_test(_make_args(name="foo"))
        assert "runtime_env" not in captured["config"]
