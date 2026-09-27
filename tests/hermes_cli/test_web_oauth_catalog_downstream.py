"""The fork derives ``_OAUTH_PROVIDER_CATALOG`` from ``provider_catalog.OAUTH_FLOW_OVERRIDES``.

Upstream keeps the rows inline in ``hermes_cli/web_server_oauth.py``. The derived tuple must equal
upstream's field-for-field (``status_fn`` aside, which the fork attaches by id). ``_UPSTREAM_ROWS``
is upstream's row set at 2f14d5e6e4e (merge 2026-09-27, which renamed the anthropic card to
"Anthropic Account"); when a merge brings a row edit, this literal and ``OAUTH_FLOW_OVERRIDES``
move together.
"""
from hermes_cli import web_server_oauth as oauth

_UPSTREAM_ROWS = (
    {"id": "nous", "name": "Nous Portal", "flow": "device_code",
     "cli_command": "hermes auth add nous", "docs_url": "https://portal.nousresearch.com"},
    {"id": "openai-codex", "name": "ChatGPT or Codex Subscription", "flow": "device_code",
     "cli_command": "hermes auth add openai-codex", "docs_url": "https://platform.openai.com/docs"},
    {"id": "qwen-oauth", "name": "Qwen (via Qwen CLI)", "flow": "external",
     "cli_command": "hermes auth add qwen-oauth", "docs_url": "https://github.com/QwenLM/qwen-code"},
    {"id": "minimax-oauth", "name": "MiniMax (OAuth)", "flow": "device_code",
     "cli_command": "hermes auth add minimax-oauth", "docs_url": "https://www.minimax.io"},
    {"id": "xai-oauth", "name": "xAI Grok OAuth (SuperGrok / Premium+)", "flow": "device_code",
     "cli_command": "hermes auth add xai-oauth",
     "docs_url": "https://hermes-agent.nousresearch.com/docs/guides/xai-grok-oauth"},
    {"id": "copilot-acp", "name": "GitHub Copilot (ACP)", "flow": "external",
     "cli_command": "copilot login", "docs_url": "https://docs.github.com/en/copilot"},
    {"id": "anthropic", "name": "Anthropic Account", "flow": "external",
     "cli_command": "hermes auth add anthropic",
     "docs_url": "https://docs.claude.com/en/api/getting-started"},
    {"id": "claude-code", "name": "Anthropic OAuth: Required Extra Usage Credits to Use Subscription",
     "flow": "external", "cli_command": "claude setup-token",
     "docs_url": "https://docs.claude.com/en/docs/claude-code"},
)

_UPSTREAM_STATUS_FNS = {
    "copilot-acp": oauth._copilot_acp_status,
    "anthropic": oauth._anthropic_oauth_status,
    "claude-code": oauth._claude_code_only_status,
}


def test_derived_catalog_equals_upstream_rows_field_for_field():
    derived = tuple(
        {k: v for k, v in row.items() if k != "status_fn"} for row in oauth._OAUTH_PROVIDER_CATALOG
    )
    assert derived == _UPSTREAM_ROWS


def test_derived_catalog_attaches_upstream_status_fns():
    assert {row["id"]: row["status_fn"] for row in oauth._OAUTH_PROVIDER_CATALOG} == {
        row["id"]: _UPSTREAM_STATUS_FNS.get(row["id"]) for row in _UPSTREAM_ROWS
    }
