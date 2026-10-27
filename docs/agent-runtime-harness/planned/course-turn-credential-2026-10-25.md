# Planned — the course credential reaches a persona's turn without riding argv (RT-COURSE-AUTHORING-PERSONA-TOOL, 2026-10-25)

**Owner domain:** the chat turn lane ([05-chat-turn-lane.md](../05-chat-turn-lane.md)), multi-device credentials
([09-multi-device-runtime.md](../09-multi-device-runtime.md) § Realm sync credentials). Parent plan:
[realm-course-subject-authoring-2026-10-21.md](../archive/realm-course-subject-authoring-2026-10-21.md) §3 C3 and § Open
rulings (the Launcher brokers the credential and passes it inline — recommended there, taken here).
**Status:** RULED 2026-10-25 (lane w1025b-h-misc, by the wave brief's "go with recommendations"); build rows in §4.
**Read:** hermes `origin/main` `eed79e6933` — `agent_runtime/chat_turn.py::normalize_chat_message` and
`ChatTurnRequest` (`argv` is the turn's MESSAGE: it is fingerprinted and written into the accept receipt by
`reserve_chat_turn` → `verify_payload` / `mark_accepted`), `hermes_cli/harness_parts/serve/lanes.py::_spawn_chat_turn`
(the turn runs on the SERVE's pool, in the serve process, through `_ArgvRequest` → `_run`), and
`agent_runtime/course_authoring.py` (`parse_credential`, `checkout`, `commit`, `pull_request`).

## 1. The problem, measured

A `mission.chat.message` param becomes argv, and argv is durable: the receipt keeps it to answer a replay and
to refuse `turn_payload_conflict`. A credential there would sit in the store root for the receipt's life and
in every replay ack. The turn itself, though, runs in the serve process (the resident actor), so the
credential never needs to leave memory.

## 2. Decisions (`Decided (plan):`)

1. **A turn-scoped secret map in the serve process, keyed by `turn_request_id`.** New
   `agent_runtime/turn_secrets.py` (`stores`, process-global declared with its reset): `put(turn_request_id,
   name, value, expires_at)`, `get(name)` for the CURRENT turn, `drop(turn_request_id)`. Never written to disk,
   never logged; values are held only as the parsed `RealmSyncCredential`.
2. **The method lane strips the credential before argv is built.** `normalize_chat_message` reads
   `course_credential` (added to `CHAT_MESSAGE_PARAMS`, so the manifest advertises it), parses it with
   `course_authoring.parse_credential` (an invalid or expired one refuses at the door with the module's own
   `course_credential_invalid` / `_expired`), and returns it on `ChatTurnRequest.secrets` — a field kept OUT of
   `argv` and out of the fingerprint, exactly as `delivery_flags` is. A replay with or without the credential
   is the same message.
3. **Bound for the turn's duration only.** `_spawn_chat_turn` puts the secrets under the turn id before the
   pool runs it and drops them in the same `finally` that settles the turn; the turn handler sets a
   contextvar with its `turn_request_id`, which `turn_secrets.get` reads. A turn that ends, fails or is
   cancelled leaves nothing behind; a credential past `expires_at` reads as absent.
4. **Three persona tools in the harness composite.** `course_checkout`, `course_commit`,
   `course_pull_request` in `harness_toolset.py`'s composite, each taking `course_public_id` and calling the
   shipped `course_authoring` verb with the turn's credential; with none they refuse
   `course_credential_missing` ("ask the operator to start the turn from the course editor"). The tools never
   echo the credential, and `git_authorization` stays out of every receipt (C3's existing test).
5. **The argv lane gets no credential path.** A CLI `mission-chat message` cannot carry one; a local operator
   uses the `runtime.course.*` verbs directly. A second spelling would be a second door.

## 3. Out of scope

The `pull_requests: write` App permission (an owner GitHub setting; C3 already maps the 403 to
`pull_request_not_permitted`); the Launcher's course editor UI.

## 4. Build rows

- hermes `RT-COURSE-TURN-SECRETS` — §2.1–2.3: `turn_secrets.py`, `ChatTurnRequest.secrets` outside argv and the
  fingerprint, `course_credential` in `CHAT_MESSAGE_PARAMS`, put/drop in `_spawn_chat_turn`. Killing mutations:
  fold the secret into argv → the receipt-bytes test reds; skip the drop → the after-turn `get` test reds.
- hermes `RT-COURSE-PERSONA-TOOLS` — §2.4, after `RT-COURSE-TURN-SECRETS`.
- launcher (filed by the orchestrator): the course editor's "ask the agent" send brokers `clone-credential` and
  passes it as `course_credential` on `mission.chat.message`.
