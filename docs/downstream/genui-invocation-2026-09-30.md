# GenUI invocation provenance - 2026-09-30

Launcher owns one generated document and history. Hermes supplies the exact
invoking conversation/turn through its existing app-function connection; no
artifact renderer or document store was added to Hermes.

The contract lives in [Transport and Wire](../agent-runtime-harness/03-transport-and-wire.md#launcher-generated-output-invocation-identity).
Native workers, profile discussions and operator turns have focused passing
proofs. Discussion reads never retarget a connection. Later admitted messages
bind their connection only after earlier work settles; End clears retained links.

Killing mutation: omitting `LauncherLink.request`'s invocation stamp fails the
wire test with `KeyError: invocation`, exit 1. Original code was restored.
The extended tooling run found the existing duplicate-helper and discussion
routing-baseline failures, reproduced on unchanged main. The operator method's
new scope initially exceeded its line limit by two; concise context comments
bring it below the unchanged ceiling without adding another helper or authority.
All 66 final runtime, refusal, invocation and legibility checks pass.

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
