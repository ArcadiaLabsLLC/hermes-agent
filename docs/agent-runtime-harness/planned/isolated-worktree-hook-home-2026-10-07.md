# Isolated worktree post-merge inherits operator home

2026-10-07, lifecycle fixture lane. No hook/installer implementation change.

An isolated developer source worktree was created from main8a5c19d4 and fast-forwarded to parent-reviewed39964eb11f1470c7d16bcf8c03a56289c2189efc. The per-clone `core.hooksPath` was the absolute primary checkout path `X:/Eternia/hermes-agent/.githooks`; Git shares it across worktrees. The post-merge hook invoked `python "$repo_root/scripts/verify_harness_skill_install.py"` with inherited `HERMES_HOME=X:/Eternia/.hermes`.

The verifier default repairs then verifies. Its home resolution accepts inherited `ETERNIA_HERMES_HOME`, then `HERMES_HOME`, then machine configuration, and has no developer-worktree/install ownership guard. A differing source package is copied into the inherited home before verification. This is an isolation hazard even though this occurrence was a no-op.

Actual output named four canonical packages, source in the isolated checkout, installed path `X:/Eternia/.hermes/shared/skills`, and `ok — every canonical package installed and current`. It emitted no `refreshed from the repo` line. The verifier emits that line iff any `SkillInstallResult.changed` is true; `agent_runtime/skill_install.py` performs its writes only in that changed arm.

Read-only corroboration (all content hashes, not just entrypoint):
- harness-charsheet-authoring: identical complete file hash map; latest installed mtime 2026-09-29T02:23:31.778187+00:00.
- harness-dev-delivery: identical complete file hash map; latest installed mtime 2026-10-01T17:16:38.443770+00:00.
- harness-qa-verdict: identical complete file hash map; latest installed mtime 2026-10-04T19:23:15.815859+00:00.
- harness-runtime-model: identical complete file hash map; latest installed mtime 2026-10-06T01:37:01.683176+00:00.

No pre-merge file baseline was captured; the no-op conclusion relies on native changed-report control flow and corroborating older mtimes/current content, not merely an `ok` string. No primary stamp, serve or install behavior was intentionally changed; no rollback was attempted.

Mitigation for this fixture only: every further Git command uses per-command `-c core.hooksPath=<isolated empty hook directory>`. Every spawned runtime or script receives explicit isolated `HERMES_HOME` and `ETERNIA_HERMES_HOME`. No global hook configuration changes. Durable hook behavior is a separate hygiene task.
