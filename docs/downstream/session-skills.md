# Session skills inspection

Owner-approved client-neutral read capability, 2026-09-24. Intelligence is the
first consumer; neither the service nor the wire contract depends on chat UI.

## Ownership

- `agent_runtime/skill_inspection.py`: bounded document facts from injected
  discovery/resolution functions; no second catalog or usage writer.
- `tools/skills_tool.py` → `skill_inspection_reader()`: public binding to the
  existing profile/shared/project roots, trust, quarantine, environment,
  platform, disabled-name and collision rules. Only registered plugin skills
  participate; inspection never discovers or activates plugins.
- `agent_runtime/skill_activity.py`: evidence from actual `skill_view` tool
  calls/results, shared by live notifications and persisted history.
- `agent_runtime/acp_skills.py`: capability negotiation, exact live-session
  lookup and workspace scope. Unknown sessions are never implicitly restored.
- `SessionManager.skill_history()`: existing SessionDB display lineage,
  including pre-compression messages; no parallel activity database.

ACP runs within its selected process profile. Workspace context is bound for
each read; a replaced session or changed workspace refuses the result.
Browsing never preprocesses instructions, prompts for credentials, loads a
skill into the model, installs anything or writes usage. Existing quarantine
scanning may maintain its own security cache.

## Wire v1

Initialization advertises `agentCapabilities._meta.hermesSkills` with
`version: 1`, `list: true`, `detail: true`, `loadActivity: true`.

Client methods `_hermes/skills/list`, `_hermes/skills/detail` and
`_hermes/skills/history` require `sessionId`; detail also requires `skillId`.
Every successful response repeats `version` and `sessionId`.

- List: `skills` with `id`, `name`, `description`, `category`, `tags`, `status`.
  Status is `available`, `disabled` or `tool_unavailable`; visibility does not
  grant permission to load.
- Detail: `skill` repeats list fields and adds full raw `content`, `source`,
  SHA-256 `contentHash` and declared `metadata`. The document cap is 1 MiB;
  encoded responses must also fit the client's 1 MiB line budget. Oversized
  content is refused, never silently shortened.
- History: `loaded: [{id, count}]` and `historyComplete`. Database absence
  returns the available in-memory evidence with incomplete coverage when
  earlier activity cannot be established.
- Tool updates: `_meta.hermesSkill: {id, status}` on the existing correlated
  `toolCallId`. Status is `loading`, `loaded` or `failed`. Only successful
  instruction loads count; reference-file reads and prose mentions do not.

`loaded` means instructions were returned to the agent. It does not establish
ongoing reasoning use, successful application, or that the current document
is byte-identical to what was loaded earlier. Names absent from today's catalog
remain historical evidence, not clickable current instructions.

Errors use normal ACP refusal codes. `-32010` carries a typed `reason`:
`unavailable`, `document_too_large`, `response_too_large`, `read_failed`.
No install, sync, execution, enable/disable or assignment operation is added.

## Proof

`tests/agent_runtime/test_skill_inspection.py` exercises actual A→B→A profile
roots, trusted workspace admission, disabled inspection, collision refusal,
full raw content and bounds. `tests/acp_adapter/test_skills_extension.py`
exercises negotiation, exact sessions, persisted transcripts and tool metadata.
`tests/agent_runtime/test_skill_activity.py` rejects false use evidence.
Forcing failed calls to report `loaded` makes both activity tests red; restored
behavior passes. Cross-client acceptance is recorded in
`EterniaLauncher/docs/companion/planned/SKILLS_SLICE_2026-09-24.md`.
