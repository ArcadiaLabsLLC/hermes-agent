"""Fork-owned half of ``tests/agent/test_bedrock_integration.py``.

Fork hardening of the bedrock default-region case: the AWS config and
credential lookups point at missing paths and IMDS is off, so the assertion
reads the code's us-east-1 fallback, not the developer's ~/.aws. Upstream's
autouse ``_boto_sys_modules_hygiene`` is imported by name.
"""

from __future__ import annotations

from unittest.mock import patch

from tests.agent.test_bedrock_integration import (  # noqa: F401 — upstream names the moved tests use
    _boto_sys_modules_hygiene,
)


class TestRuntimeProvider:

    def test_bedrock_runtime_default_region(self, monkeypatch, tmp_path):
        from hermes_cli.runtime_provider import resolve_runtime_provider

        monkeypatch.setenv("AWS_PROFILE", "default")
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        # Fork hardening: pin the AWS config/credential lookup at paths that do
        # not exist and disable IMDS so the assertion below reads the code's
        # us-east-1 fallback rather than whatever region the developer's real
        # ~/.aws profile or an EC2 metadata endpoint happens to advertise.
        monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "missing-config"))
        monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "missing-credentials"))
        monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

        with patch("hermes_cli.runtime_provider.resolve_provider", return_value="bedrock"), \
             patch("hermes_cli.runtime_provider._get_model_config", return_value={"provider": "bedrock"}):
            result = resolve_runtime_provider(requested="bedrock")

        assert result["region"] == "us-east-1"
