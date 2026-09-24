# Fork features the upstream website does not document

The fork does not edit upstream's `website/` pages (the upstream-footprint
ledger's movable-carry rule, `docs/agent-runtime-harness/planned/disposition-misc-2026-09-24.md`
§5). The operator-facing notes it used to write into those pages live here,
one section per page they came from. Upstream's pages are as upstream ships them.

## MCP: one-shot stdio env overrides

Was: `website/docs/guides/use-mcp-with-hermes.md` and
`website/docs/reference/mcp-config-reference.md`. Implementation:
`agent_runtime/mcp_environment.py`, `hermes mcp test --env`.

#### Per-run environment overrides (stdio servers)

For values that should only exist for a single discovery/test run — temp
file paths, nonces, local ports, one-shot credentials — use one of the two
non-persistent override surfaces. Neither writes back to `config.yaml`.

**Interactive: `--env` on `hermes mcp test`**

```bash
## Inject RUNTIME_FILE just for this probe; it never lands on disk.
hermes mcp test launcher-qa --env RUNTIME_FILE=/tmp/qa-runtime.json
```

The CLI prints `Applied 1 one-shot env override(s): RUNTIME_FILE` so you
can confirm what was injected. Values are never printed.

**Automation / wrappers: `HERMES_MCP_ENV_<SERVER>_<KEY>`**

```bash
HERMES_MCP_ENV_LAUNCHER_QA_RUNTIME_FILE=/tmp/qa-runtime.json \
  hermes mcp test launcher-qa
```

PowerShell equivalent (POSIX `KEY=VALUE cmd` syntax does not work on
PowerShell — set the env var first, then run):

```powershell
$env:HERMES_MCP_ENV_LAUNCHER_QA_RUNTIME_FILE = "C:\Temp\qa-runtime.json"
hermes mcp test launcher-qa
```

The `HERMES_MCP_ENV_<SERVER>_<KEY>` form applies to every stdio MCP
discovery path for that server, not just `hermes mcp test`. The
`<SERVER>` token is the server's configured name uppercased with every
non-alphanumeric run replaced by `_` (so `launcher-qa` →
`LAUNCHER_QA`). The reference section below has the full merge precedence and security notes.

### One-shot stdio env overrides

Durable `env` (above) is the right place for long-lived environment values that
belong with the server definition. For values you want to inject **for a
single run** — temp file paths, nonces, local ports, short-lived credentials —
Hermes supports two non-persistent override surfaces. Neither writes anything
back to `config.yaml`.

| Surface | Where set | Scope |
|---|---|---|
| `hermes mcp test <name> --env KEY=VALUE` | CLI flag | The single `mcp test` invocation |
| `HERMES_MCP_ENV_<SERVER>_<KEY>=value` | Parent process env | Every stdio MCP discovery/session for that server in this process |

Both layers are merged on top of the safe baseline and the durable `env`. The
final merge order, lowest to highest precedence, is:

1. Safe baseline (`PATH`, `HOME`, `USER`, `LANG`, `LC_ALL`, `TERM`, `SHELL`,
   `TMPDIR`, plus all `XDG_*` variables) from the parent process.
2. Durable `mcp_servers.<name>.env` from `config.yaml`.
3. Process-level namespaced overlay (`HERMES_MCP_ENV_<SERVER>_<KEY>`).
4. CLI `--env KEY=VALUE` overlay (currently only on `hermes mcp test`).

#### Server-name normalization

For the `HERMES_MCP_ENV_<SERVER>_<KEY>` form, the server name is uppercased and
every run of non-alphanumeric characters becomes a single `_`:

| Configured name | Env prefix |
|---|---|
| `launcher-qa` | `HERMES_MCP_ENV_LAUNCHER_QA_` |
| `stagec-launcher-qa` | `HERMES_MCP_ENV_STAGEC_LAUNCHER_QA_` |
| `my.server` | `HERMES_MCP_ENV_MY_SERVER_` |

Note that `foo-bar` and `foo_bar` both normalize to `FOO_BAR_`. If you use
similar names, pick distinct ones.

#### Security model

Hermes deliberately does **not** inherit arbitrary parent env vars into MCP
subprocesses — see the safe-baseline list above. The two override surfaces are
the explicit opt-in:

- The `HERMES_MCP_ENV_<SERVER>_<KEY>` prefix is the namespace boundary. A
  parent env var without that prefix will not cross into the child.
- `--env` is an explicit per-run flag.

Hermes never logs override values. The CLI prints the count and key names
(`Applied 2 one-shot env override(s): RUNTIME_FILE, TOKEN`) but not values.

#### Caveats

- Don't put long-lived secrets in shell history. Prefer temp files or a secret
  manager and inject the resolved value into the env immediately before the
  command.
- On Windows PowerShell, inline POSIX-style `KEY=VALUE cmd` syntax does not
  work. Use `$env:HERMES_MCP_ENV_FOO_TOKEN = "…"; hermes mcp test foo` or a
  short `.ps1` wrapper.

## Docker: `gateway.port` is not the API server port

Was: `website/docs/user-guide/docker.md`. Upstream's page says no
`config.yaml` key sets the OpenAI-compatible API server's port (8642). A
`gateway.port` key does exist in the fork's `config.yaml`, but it belongs to the
agent-runtime remote gateway (the serve socket lane) and has no bearing on the
API server: setting it will not move port 8642.

## Kanban: crash artifacts

Was: `website/docs/user-guide/features/kanban.md`. Implementation:
`hermes_cli/kanban_crash_evidence.py`. The fork's `crashed` task event carries
more than upstream's row lists:

| Event | Payload | Meaning |
|---|---|---|
| `crashed` | `{pid, claimer, exit_kind?, exit_code?, worker_output?, classification, evidence_path, alive_sidecar_pids?}` | Worker PID no longer alive but TTL hadn't expired yet. `worker_output` is the tail of the worker's own log (its final response or the rendered provider error, chrome stripped, ≤ 400 chars) and is also appended to the task's `last_failure_error`, so the board shows *why* instead of only the exit code. `classification` is `supervisor_lost_child` when a detached sidecar (e.g. an encoder, training loop) is still running, else `process_failed`. `evidence_path` points to a redaction-safe JSON crash artifact under `<board logs>/crashes/<task>-<epoch>-<rand>.json` that captures the bounded worker-log tail, sidecar manifests, and per-sidecar log tails — see "Crash artifacts" below. |

#### Crash artifacts

Every `crashed` event also writes a durable JSON artifact under
`<board logs>/crashes/<task>-<epoch>-<rand>.json`. The path is referenced from
both the `crashed` event payload's `evidence_path` field and the closed run's
`task_runs.metadata.evidence_path`. The artifact is deterministic (sorted keys
+ atomic temp-rename) and redacts Bearer/JWT/`Authorization`/cookie/`X-Amz-*`/
`Signature`/`Expires`/`--token=`/`api_key`-style values from every captured
log tail. Fields:

- `classification` — `supervisor_lost_child` (≥1 detached child still
  running, recovery can attach) or `process_failed` (everything is dead,
  clean failure).
- `worker_pid`, `claimer`, `exit_kind`, `exit_code`, `error`.
- `workspace_path`, `worker_log_path`, `worker_log_tail` (bounded ≤8 KiB,
  redacted), `worker_log_growing` (true when the log was touched in the
  last 120 s — useful when a detached child is still writing through the
  supervisor's log fd).
- `sidecars[]` — discovered from `<workspace>/.hermes/sidecars/*.json`
  (also accepts `.sidecars/` and `sidecars/`). Each entry carries `pid`,
  `cmd`, `cwd`, `name`, `log_path`, `log_tail` (redacted, bounded), and
  `alive`. JSON manifests should include at least `{"pid": …}`; plain
  `*.pid` files containing a single integer are also accepted. A
  recovery task can use this list to re-attach to the surviving child
  without re-deriving its argv.
- `captured_at_epoch` + ISO `timestamp` for ordering.

Sidecar discovery is bounded (8 entries, 32 KiB per manifest, 8 KiB per log
tail) so a malformed workspace cannot stall the dispatcher tick. Artifact
write failures degrade silently — the `crashed` event still records the
pid + exit info, just without an `evidence_path`.

## Tool search: `never_defer`

Was: `website/docs/user-guide/features/tool-search.md`. Implementation:
`tools/tool_search.py`.

```yaml
tools:
  tool_search:
    never_defer: []     # extra tool names that always ride eagerly
```

| Key | Default | Meaning |
|---|---|---|
| `never_defer` | `[]` | Extra tool names that always ride eagerly instead of deferring behind the bridge. Extends the built-in set (`agent_chat_send`, `agent_chat_dispatches`); cannot remove built-ins. Un-hides only — a tool must still be granted by the session's toolsets. |

## Messaging: background-completion notifications

Owner ruling 2026-09-24 (lane DOORS-A): the fork no longer gates background-completion
agent turns. A background `terminal` spawn notifies on exit by default (the
eternia-harness plugin defaults upstream's `notify` on at spawn; `notify=false` opts
out) and completion runs an agent turn, upstream's behaviour — the former
`display.background_process_agent_turns` key and `HERMES_BACKGROUND_AGENT_TURNS` are gone.
In Mission Control the serve drain delivers it: a busy turn is steered, an idle thread
gets a turn, an orphaned chat root drops it. `display.background_process_notifications`
is upstream's (`concise`).
