# Layout sheet — the W0-G6-undeclared population (lane LAYERS-DESIGN, 2026-09-25)

Base: `origin/main` @ `478fcc5ba5`. Rules the two `runtime-queue.md` rows marked `TAKEN 2026-09-25 lane LAYERS-DESIGN` — the 66-module row (lane W3-B, `24763b9a8e` / `60c0309dfc` / `cc22bb16b3` / `c37726d912`) and the three-upward-edge row (lane 2B-B). Bar: `god-file-program-2026-09-24.md` §2 rule 16 and gate W0-G6 (§2.4). Design only — no code changes in this lane.

## 1. Population and method

**Population.** 66 modules, read from the probe itself (`scripts/god_file_probe.py`, `layer_census()["undeclared"]` at the base — byte-equal to `tests/fixtures/import_layers_grandfathered.json`'s `undeclared` list; the fixture was not retyped). 30,457 raw lines. Every one is under `agent_runtime/` except `agent/charsheet/fake_draftsman.py`. Plus the three modules of the second row (`persona_chat_history/curation.py`, `persona_chat_history/markers.py`, `harness_parts/persona/chat_history_writes.py`) — see §2.4.

**Method** (the three facts per module, all computed, none copied from W3-B's commit bodies):

- **reach** — the highest layer the module's imports touch, read exactly as the gate reads them (`imports_of`: module-level AND deferred imports both count; a `from agent_runtime.<pkg> import name` resolves to `<pkg>/__init__.py`'s layer, because `layer_violations` looks one `rsplit` up and no further). Reach is taken TRANSITIVELY through undeclared imports, because an undeclared import is invisible to the gate today and becomes an edge the moment that module declares — the planning instrument must see the edge the exec lane will create.
- **cap** — the lowest layer among the module's DECLARED importers; a declaration above the cap is an upward edge from that importer.
- **raw** — `wc -l`.

Three classes account for every gap between reach and cap; the verb per module in §2 names which:

| class | what it is | verb |
|---|---|---|
| **A · package-door reach** | the module imports a name from a package `__init__` declared at the package's TOP layer, while the name is defined in a lower submodule (`from .serve_rpc import ERR_CONFLICT` → `serve_rpc/__init__` is `lanes`, `ERR_CONFLICT` lives in `serve_rpc/protocol.py`, `models`). 15 of the 66 carry one. | MOVE the import to the owning submodule — a respelling, no code moves |
| **B · a low-layer fact stranded in a high module** | a vocabulary constant or a pure helper defined in a stores/lanes module and read by a models/policy module (`EVENT_PAYLOAD_LIMIT_BYTES` in `events.py`, `ProjectionAccountant` in `parity.py`, `stamp_passed` in `store_file_io.py`). | MOVE the symbol down; the high module re-imports it |
| **C · a declared importer whose layer is wrong** | a module declared `policy`/`models` that reads a store or a live process fact (`root_observability` reads the process chat scope; `mcp_admission/resolve` reads readiness and registrations; `serve_rpc/registry` lazily imports three handler modules). | RE-DECLARE the importer, after checking ITS importers admit the new layer (every one listed in §2 was checked) |

After A–C are applied, 33 of the 66 have no upward edge at all and simply DECLARE — their W3-B cap reason was a chain through another undeclared module, not an edge of their own.

**Decision rules applied** (the brief's, plus two the population forced): a module doing store I/O is `stores` whatever its name says (`serve_gateway_auth`, `chat_reply_stamps`, `provider_visibility`, `harness_doctor/model` all re-declare on this rule); a module read by ONE importer folds into that importer's package rather than getting a layer (no instance survived — every single-importer module here is already inside its importer's package, `discussions/native.py`, or is imported by a flat file); a declaration goes at the layer of the module's WORK, bounded by cap and reach — never "the lowest layer the imports allow" (that reading makes an RPC handler `stores` and hides the next upward edge behind it); a cycle between two modules is legal to the gate and is left alone unless a fact in it belongs lower.

**The gate today.** `tests/tooling/test_fork_import_layers.py` runs at the base (11 passed, 12.8 s, the `acp` pin of `478fcc5ba5` removed the runtime arm's blocker the second row names). It reports **no** live violation: the one edge the census surfaced — `serve_rpc/registry.py` (`models`) → `local_llama_adapter/rpc.py` — is not a gate edge because `rpc.py` is undeclared; it BECOMES one in the first exec lane that declares `rpc.py`, `discussions/rpc.py` or `chat_turn.py`, which is why the registry re-declare is pinned to lane L1 in §3.
