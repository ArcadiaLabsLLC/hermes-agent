# Shared provider authority — September 29

Owner-approved correction: connect once to the selected Hermes service; choose
provider/model per agent or conversation without copying credentials.

## Ownership

- The service captures its existing `HERMES_AUTH_HOME` authority, or its own home.
  Conversation workers receive that exact owner. In-process workers bind the same
  ContextVar; they never change process-global environment.
- Existing credential pools, OAuth readers, provider inventory and model resolver
  remain authoritative. Provider-only readers consult the bound owner; profile
  secrets used by tools, skills, transcripts and terminal policy stay independent.
- Shared definitions are an ephemeral projection at provider readers, not config
  inheritance or a second catalog. Unbound standalone profiles retain their
  original behavior. Missing owner credentials never borrow an agent's key.
- New conversations use the agent's configured model; an unconfigured agent uses
  the service default. An explicit agent-default edit uses Hermes's existing
  config writer. It does not change other open conversations.
- Native `runtime.conversation.model` accepts optional `save_default: true`.
  Current/default identities must both be confirmed before returning success.
  Managed configuration refuses default writes. Busy or uncertain work is not
  reconfigured, restarted or replayed.

## Native gaps repaired

The real compute-child test exposed missing model/provider identity in lazy
recovery. Both projections now reuse `_live_session_identity`.

An idle compute-backed session previously deferred even an explicit Apply. The
existing supervisor now forwards `config.set.model` to the existing child and
returns its native receipt. Busy sessions retain their queued-switch behavior.
No second agent, model state, transport or restart loop was added.

In-process execution exposed lost auth-owner context at agent-build and prompt
threads. Both now use the existing `spawn_context_thread` helper.

Thin upstream seams and retirement conditions are recorded in the
[footprint ledger](../agent-runtime-harness/planned/upstream-footprint-ledger.md).

## Evidence

- `test_native_conversation_roundtrip.py`: four real loopback-provider variants
  (private/shared × inline/compute), A→B→A profile isolation, retirement/reopen,
  and confirmed changes before and after execution. A later request demonstrably
  uses the newly selected model.
- `test_native_conversation_in_process.py`: four checks, including shared and
  private A→B→A execution with no worker subprocess.
- `test_shared_provider_credentials.py` and
  `test_shared_provider_configuration.py`: owner A→B→A, existing pool/resolver,
  OAuth store ownership, no copied credentials, preserved tool/config scope and
  existing default writer.
- Nineteen focused native/upstream files: **340 passed**. Log:
  `qa-artifacts/shared-provider-regressions.log` (ignored).
- Execution variants: **8 passed**. Log:
  `qa-artifacts/shared-provider-execution-green.log` (ignored).
- Native retention, admission fencing, rejected/uncertain model writes, generated
  contracts, size and footprint gates: **28 passed**. The same batch exposed two
  stale recovery fixtures after upstream's `5eea87882a` clarification-format change.
- Updated fixtures use upstream's question-list and answer-map contract. Real
  inline/compute recovery, repeated answer acknowledgements, exact Stop and
  10 MiB history recovery after restart pass: **11 checks**, including the footprint
  gate. Log: `qa-artifacts/shared-provider-live-recovery.log` (ignored).
- Launcher-to-native compute integration: **2 passed**, covering reconstructed
  Direct/Compare clients, independent participants, exact question replies and
  lost submission/Stop acknowledgements. Launcher log:
  `build/shared-provider-cross-runtime.log` (ignored).
- Config-writer gate passes; changed-line profile-scope audit reports no findings.

Recorded red controls: missing lazy identity fails the model receipt; deferred
idle compute selection fails after a completed turn; plain background threads
fail shared in-process execution. Each passes with its corresponding repair.

No real provider credentials, user profiles or production sessions were modified
by these tests. This is not a live-provider or whole-repository qualification.

The doc-citation gate reports two unrelated stale line references: boot/lifecycle
to `core_cache/lane.py`, and observability to `context_store.py`. The referenced
files, citations and gate are unchanged from base `85920eadc4`; these remain in
the fork-hygiene queue. No citation waiver was added.

## Installed update

Provider change `ccca4c3138` is included in installed fork main `a58b3c7dbc`.
The canonical updater completed after enabling Windows certificate-store trust
for uv; certificate verification was not disabled. The success receipt and live
gateway agree on the new revision, with Amelia among eight served profiles.
Upstream migrated the gateway to its shared-host topology and seeded six missing
profile `.env` files from default tool settings; those contained no configured
provider secrets. Desktop was untouched.

Quick snapshots covered every profile but skipped Amelia's 3.9 GiB history by
size. The full backup contains all eight profile databases and 1,698 files. It
is marked incomplete solely because the live `agent-runtime/serve_socket.lock`
could not be read; the archive is retained for recovery. Excluding runtime locks
from that upstream backup classification is separate maintenance, not a reason
to weaken profile protection or create another backup implementation.
