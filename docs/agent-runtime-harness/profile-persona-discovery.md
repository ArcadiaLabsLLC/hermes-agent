# Local Hermes profile → Persona discovery

Mission Control's default-store snapshot now reconciles **live named Hermes profiles** into durable Persona definitions before consulting its persisted snapshot cache. A newly created profile becomes a Persona on the next snapshot after the 15-second discovery window; a runtime restart is not required. The Launcher consumes the existing `agents` and `available_personas` snapshot fields; it does not choose or change the Hermes executable.

- A profile is eligible only if the Hermes CLI lists it as live and it has a servable identity marker. The `default` profile, deleted profiles, ghost directories, and crash shells containing only an empty `.env` are not promoted **or offered as placeable templates**. The metadata-only roster now shares those filters (`hermes_cli/profiles.py`).
- An existing store or config Persona bound to that profile wins. Discovery does not overwrite it or choose among multiple owners.
- New definitions have deterministic IDs (`profile_<name>`), the `profile` role, proposal-only autonomy, inherited profile memory, and no invented toolset grant. An occupied ID with a different binding is logged and skipped, not overwritten. Later edits to a generated Persona remain operator-owned.
- No PersonaInstance, Office placement, chat, process, or agent run is started. This is identity registration only; placement and execution remain explicit actions.
- Discovery uses the selected Hermes runtime's profile root. It never reads credentials or alters a Launcher selection. Failures are logged and retried on the next snapshot instead of silently classifying profiles as absent.

Implementation: `agent_runtime/profile_persona_discovery.py`, invoked by `agent_runtime/snapshot/` only on the default-store path. The config/store merge `ensure_persisted_personas` stays read-only. Hermetic tests in `tests/agent_runtime/test_profile_persona_discovery.py` cover real profile discovery, a second profile appearing while running, idempotence, manual/config ownership, collisions, crash shells, and scan failures.
