---
type: adr
id: 0009
status: accepted
date: 2026-08-15
tags: [adr, runtime, mcp, security]
---

# 0009 — Profile declaration is the sole MCP admission authority

> [!summary]
> Which MCP servers a persona's turn may reach is decided ONLY by the profile's declaration (`agent_runtime/mcp_admission.py`: `resolve_mcp_admission` → `admit_mcp_servers`, with `McpCallBudget`). Role fields are reporting-only. Superseded the S64/S66-era role gating.

## Context

MCP admission had two authorities — a role table and the profile declaration — and they disagreed in the field: an agent admitted by role reached a server its profile never declared. The operating-manual skill is auto-preloaded; the relay has a cycle guard (verified); cross-process MCP session discovery is a known gap.

## Decision

One authority. Admission receipts are log lines (`mcp_admission_ms`, the admitted set) and the chat-turn ledger records them; `launcher_qa` is declared for the `qa`/`dev` roles' profiles only, so a neko turn admits nothing.

## Consequences

- A "why can't my agent see tool X" question is answered by the profile's declaration, never by a role.
- The read-only allowlist profile (`READ_ONLY_ALLOWLIST_PROFILE`) exists for tests; the refactor plan moves it under `tests/`.

## Alternatives

Role-derived admission (rejected: two authorities, one of them silent).
