# GenUI invocation provenance — 2026-09-30

Launcher owns one generated document and history. Hermes now supplies its exact
invoking conversation/turn through the existing app-function connection; no
artifact renderer or document store was added to Hermes.

The contract lives in [Transport and Wire](../agent-runtime-harness/03-transport-and-wire.md#launcher-generated-output-invocation-identity).
Direct native workers (including isolated compute and in-process execution),
profile discussions and operator turns have focused passing proofs. Discussion
read/replay does not retarget the connection; a later admitted message may bind
its new connection only after preceding work settles. End clears retained links.

Killing mutation: omit `LauncherLink.request`'s invocation stamp. The new wire
test fails with `KeyError: 'invocation'`, exit 1. Original source was restored.
Tooling checks passed 1,278 assertions; the existing duplicate-helper-name check
fails on `_flag`, `_model`, `_owner`, also reproduced on unchanged main.

## Validation baseline

The full canonical suite is being qualified. Focused unchanged-main comparison
reproduced five stale chat-lane patch-target failures, the duplicate-name gate,
six office method-manifest/envelope failures, and one strict XPASS in anonymous
sign-in. Realm-sync accounting and embedded-phone checks pass when run directly;
the canonical isolated runner failures need separate classification. Existing
chat-lane/duplicate rows retain their ownership; remaining baseline work is
filed in the fork hygiene queue. No baseline or exemption was enlarged.
