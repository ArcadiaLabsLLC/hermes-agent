# Independent agent creation

Owner ruling, 2026-11-18. Every action that creates an agent gives it a new persona
and a new backing profile. Creating from an existing agent or template is a copy
of its starting configuration. It gives the new agent its own identity, files and
history.

## Entrypoints and identity

One Harness authoring operation should provision the three linked records and
return their actual IDs. Route office creation through `runtime.agent.create`,
profile-based creation through the existing `runtime.persona.instance.create` and
its CLI twin, and legacy authoring with `--add-instance` through that same
provisioning operation. Those paths currently share
`PersonaInstanceStore.add_instance` for placements, while free-standing agent
creation calls `create_operator_chat` through the CLI twin. Distinguish explicit
agent creation from a request to create a conversation for an existing agent.

The template ID stays the source identity on the request and idempotency key. The
new persona and profile IDs belong to the result. Office rows, pending UI rows,
chat routing and skill installation use the newly returned identities. Reopening
a chat, moving a desk, and pulling a published instance preserve the identity
they already address. Existing agents retain their bindings.

## Starting configuration

Copy the source's authored portable model defaults, skill choices, soul and
system prompt. Write portable files inside the new profile using owned paths.
Start with empty chat history, memory and sessions. Leave credentials, vaults,
provider tokens, environment files, gateway and device bindings, and machine
folder paths at their source. Hermes's generic profile clone copies `.env`, so
the agent authoring path needs a portable allowlist and a staged profile write.

The reserve-and-resume path needs stable destination identities before the first
durable write. A retry must reuse its own persona, profile and agent, even if
the first attempt stopped between writes. On a refused placement, compensation
can clean up only records owned by that reservation. A later skill failure
should remain retryable without recreating the agent.

## Existing cross-realm reuse

Detect a persona or backing profile already referenced by a different realm in
the current namespace. Explain which data would remain shared at the affected
share or apply decision. Offer the same **Create independent copy** action used
on an existing agent, with the destination workspace preselected. Keep the
copy action available outside realm sync too.

## Acceptance

Prove that all explicit creation doors return independent identities, the copied
persona and profile can be edited without changing the original, and retry or
rollback leaves a consistent set of records. Verify the portable-copy policy with
secret-shaped and local-only fixture data. Read the office, Agents browser and
cross-realm path through the normal product UI. Verify that an existing agent's
new chat and a realm replica keep their existing identity rules.
