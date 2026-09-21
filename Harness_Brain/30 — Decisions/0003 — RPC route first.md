---
type: adr
id: 0003
status: accepted
date: 2026-09-05
tags: [adr, transport, mission-control]
---

# 0003 — RPC route first

> [!summary]
> **Every touched write lane moves to the hermes method lane by manifest membership.** The aim decides the destination (a Mac runs the turn as its own operator's). argv is a fallback **marked for delete**. Cited as R-C4 in `planned/remote-chat-parity.md`.

## Context

Console chat send / steer / new-chat were argv-only. The C5 field run (2026-09-06) had the Mac greet and then refuse a send because the launcher's own lowering hit an argv wall (`args_not_carried:workspace_name`). R-C8 answered with the method carrying the whole verb surface plus a manifest `params` block (the 18-key message, hermes `28e502e286`, launcher `bbb82393b`).

## Decision

A write verb is a `serve_rpc` method with a `params` block; the launcher lowers by manifest membership. New argv verbs are refused. Existing argv paths are deleted when the launcher no longer lowers them (the refactor plan's §4.2 census decides which).

## Consequences

- The CLI contract fixture changes when an argv verb is deleted; the same wave re-vendors the launcher's copy.
- `dispatch_argv` itself survives — the operator's own CLI is an argv caller.

## Alternatives

Widen the argv lowering per verb (rejected: every widening is another wall waiting).
