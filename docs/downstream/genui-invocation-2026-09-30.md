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

The canonical isolated suite completed 2,175 files in 1,752 seconds, exit 1:
48 assertion failures in 29 files; 14 other files exited nonzero or did not run
successfully. This is not a green full-suite receipt.

- Corrected this slice's discussion RPC fixture: all three refusal tests pass.
  Embedded-phone packaging now passes after the new module was committed; its
  earlier run correctly refused an untracked shipped module.
- Unchanged-main comparisons reproduce stale chat-lane targets, duplicate helper
  names, office manifests, anonymous-sign-in XPASS, realm-sync/commit-build/
  doctor failures, plugin admission and environment fences, Windows path and
  relaunch assumptions, source publication, interrupted update, SQLite recovery
  and malformed-repair checks. The remaining plugin collection errors share the
  same fenced environment setup; no exemptions were added.
- Worktree-specific observations remain qualified: fleet tests classify the
  shared interpreter as external; lazy update dispatch detects the interpreter's
  other checkout. Clarify's strict XPASS is conditional. EOL churn and secret
  import-lock failures did not reproduce in the primary isolated comparison.
  These are recorded for runner qualification, not silently called passing.
- Documentation adjacency retains the existing Toolsets citation failure.
  Changed-line mutation inventory selects no additional gates.

The fork hygiene queue owns remaining baseline/runner classification. Focused
invocation and architecture proofs remain independent of those failures.
