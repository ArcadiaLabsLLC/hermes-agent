---
type: adr
id: 0001
status: accepted
date: 2026-08-13
tags: [adr, upstream, transport]
---

# 0001 — Fork boundary, PUSH vs RPC union

> [!summary]
> **We own the better PUSH, upstream owns the better CALL — build the union.** The fork's `agent_runtime` push lane (snapshot stream, folds, patch frames to the launcher) is not in upstream at all; upstream's JSON-RPC method surface is the better call lane. Neither replaces the other.

## Context

The natural assumption was the reverse: that the fork had bolted an RPC layer onto an upstream streaming runtime. Reading the trees in August 2026 showed `agent_runtime/` absent from upstream entirely, while upstream's gateway had grown a cleaner method/call lane. Planning transport work on the wrong assumption would have rebuilt what the other side already had.

## Decision

The push lane stays fork-owned and **live-on-by-default** (2026-08-17 — "dark behind a config gate" was stale by then; do not re-quote it). Call-shaped work (verbs, manifests, params blocks) rides the method lane; see [[0003 — RPC route first]]. The canon's doc 03 owns the wire boundary.

## Consequences

- Every transport plan reads this before proposing a new lane.
- Upstream merges never conflict on `agent_runtime/` — the whole push lane is fork-only ([[Fork Boundary Map]]).
- The fork's edits to upstream's gateway/CLI are the seams that DO conflict; the seam program ([[Upstream Sync]]) is where that cost is paid down.

## Alternatives

Replace the push lane with upstream's calls (rejected: the launcher's paint pipeline is the push lane's consumer, and O(world) snapshots do not fit a request/response shape); port the fork's RPC to upstream (moot: upstream's is better).
