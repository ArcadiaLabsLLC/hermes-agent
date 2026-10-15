---
type: adr
id: 0008
status: accepted
date: 2026-07-30
tags: [adr, runtime, architecture]
---

# 0008 — Chat is the only lane

> [!summary]
> The goal/task mission lane — daemon, stage graph, proof gates, role gating, blueprint graph, taskless runtime loops — was DELETED on 2026-07-30. An operator (or another agent) messages a placed persona's chat root; that is the whole product. The same-day cleanup wave purged the orphans (Stage C = MCP-only ruling, env-gap test fence, docs 17/18, archive root).

## Context

The harness had over-built orchestration before chat worked: a hardcoded role-encoded TaskState machine, then a blueprint graph meant to replace it, then goals scaling as N operator chats with tasks as an advisory HUD (entity model locked 2026-06-22). The north star was always one-shot autonomy — a goal completed unattended — but the "remaster the cathedral" ruling put a chat-first foundation under it with the harness as an escalation layer. By July the mission lane was the thing in the way.

## Decision

Delete it, and keep it deleted. The canon's 00-index documents only what remains; superseded entity-model and graph decisions are history in `archive/`.

## Consequences

- Session-memory entries about the entity model, blueprint graph and Stage 75/76 are superseded on goals/tasks; read them as history.
- Anything that looks like a new orchestration lane (a daemon, a task graph) is refused at planning unless it rides a chat turn.

## Alternatives

Keep the graph as data-only (rejected: it re-grew role gating within weeks).
