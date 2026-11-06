# Planned — how the owner's own external gateways reach an account namespace (RT-EXTERNAL-GATEWAY-NAMESPACE-ACCESS, 2026-11-05)

**Status:** options and a recommendation, written by lane w1105g-hm-plan; **the shape is the owner's call**
(`RT-EXTERNAL-GATEWAY-SHAPE-RULING`, BLOCKED owner decision). Build rows in §5 wait on that ruling. Group:
`external-gateway-access`.
**Owner domain:** the namespace boundary ([04-boot-and-lifecycle.md](../04-boot-and-lifecycle.md) § the profile
namespace) and the serve's transports ([03-transport-and-wire.md](../03-transport-and-wire.md) §1.1, §1.4;
[09-multi-device-runtime.md](../09-multi-device-runtime.md) § Credentials, § The operator's remote turn).
**Owner, 2026-11-05:** "im going to build my own external gateways … we need to think about how it will use it."
**Read (code, no live run):** hermes `origin/main` `864cf9b45c` — `hermes_cli/_namespace_bootstrap.py` (the
outside-launcher rule, the fences); `agent_runtime/serve_gateway_auth.py` (per-device credentials, tiers,
revocation); `agent_runtime/call_authorization.py` (the tier is read off the caller); `agent_runtime/serve_rpc/
chat.py::_runtime_chat_message` (a chat turn is `console` tier, and why); `gateway/platforms/base.py::
_acquire_platform_lock` (upstream's one-holder-per-token lock); the archived row `RT-GATEWAY-SERVICE-OUTSIDE-
NAMESPACE` (the alice gateway's move into `acct-26858805fff7de3b`, launcher `d97a3fddc8`).

## 0. What is true today

- A process the launcher did not spawn reaches **only** the namespace `<base>/namespace-active.json` names — the
  "Allow agent use outside the launcher" switch — and only with `HERMES_DEPENDENCY_ROOT` naming the base root and
  `HERMES_HOME` unset (an explicit home outside the namespace refuses; one inside made the namespace its own root
  and started a dependency sync on 2026-11-05).
- The upstream gateway runs AS A PROFILE PROCESS inside it (`hermes --profile alice gateway run`): it opens the
  namespace's stores directly, a second writer beside the serve, and its Telegram turns land in `alice`'s
  `state.db` with `source: telegram`. It is started by a per-user logon task.
- One Telegram bot token sits in eight profiles' `.env`. Upstream's scoped token lock lets only one gateway poll
  it at a time; the other seven fail at start, so "which agent answers" is whichever started first.
- The serve already has a door for a process that is not the launcher: the **gateway listener** (03 §1.1) — TLS
  with a pinned per-install cert, a per-DEVICE credential minted by a pairing ceremony, a stored tier,
  revocation, no argv lane — and remote launchers already drive chat over it (`runtime.chat.message`, 09 § The
  operator's remote turn).

## 1. The options

| | A — profile process in the namespace (today's upstream shape) | B — serve client, loopback socket + root token | C — serve client, gateway listener + its own paired credential |
|---|---|---|---|
| reaches the namespace by | the external-access switch + `HERMES_DEPENDENCY_ROOT` | reading `serve_auth`'s token file | a credential the owner pairs once per gateway |
| power | everything the profile can do, stores opened directly | `local_console`: the machine owner, every verb | `console` tier (a chat turn runs tools — `chat.py` explains why nothing lower is honest), **scoped to the persona instances it is bound to** |
| writers on the stores | two (gateway + serve) | one (serve) | one (serve) |
| sessions / receipts in Mission Control | only if MC reads that profile's `state.db` | yes — the serve runs the turn | yes — the serve runs the turn, stamped with the gateway |
| revoke one gateway | delete its profile `.env` token | rotate the root token (breaks the launcher too) | `harness gateway devices revoke <device_id>` |
| language / process | must be Hermes (Python, this install) | any language that speaks the NDJSON socket | any language that speaks the gateway lane |
| runs on another machine | no | no | yes (the lane is built for it) |
| survives the launcher closing | yes (own process) | only while a serve runs | only while a serve runs (`--service` already outlives the launcher) |

## 2. Recommendation — C (vetoable; the choice is the owner's)

A gateway is a CLIENT of the namespace's serve over the gateway lane, holding its own paired credential. Why:
it is the only shape with one writer, a per-gateway revocation and Mission Control visibility for free; it lets
the owner write the gateway in any language and on any machine; and it needs no new transport — the lane, the
pairing ceremony, the tier gate and the chat verbs exist and are hardened. A stays available for the upstream
gateway until the owner's own replaces it; B is refused outright (the root token is the machine owner, and
handing it to a bot process is a door around every tier).

What C needs that the lane does not have yet, each a vetoable call:

- **D1 — a `channel` credential kind.** A paired device row gains `kind: channel` and `bound_instances` (persona
  instance ids). Its tier is `console`, and the gate adds one rule: a chat verb (`runtime.chat.message`, `.steer`,
  `runtime.persona.instance.open_chat`) naming an instance outside `bound_instances` refuses
  `channel_instance_not_bound`; every non-chat console verb refuses for the kind (a bot never retires an agent).
  Scope narrows WHICH agent, never what the agent may do.
- **D2 — one verb for an inbound message: `runtime.channel.message`.** Params `{channel_key, sender, text,
  attachments?, turn_request_id}`; `channel_key` is the gateway's own stable id for a conversation (e.g.
  `telegram:<chat_id>`). The serve maps `(gateway device, channel_key)` → one session of the bound instance,
  created on first use and reused after, and stamps the session `source: channel:<device name>` so Mission
  Control lists it with the instance's other chats. The reply rides the existing per-request frame lane. The
  gateway owns the platform side (polling, webhooks, formatting); hermes never sees a bot token.
- **D3 — which agent answers.** One gateway is bound to one or more persona instances at pairing
  (`--instance <id>`, repeatable); a `channel_key` resolves to the FIRST bound instance unless the gateway names
  `persona_instance_id` (it must be bound). Recommendation: one instance per gateway to start.
- **D4 — one bot token per gateway.** The token is the gateway's secret, in the gateway's own config — not a
  hermes profile's `.env`. The eight copies in the profile `.env` files are retired when the upstream gateway is
  (the owner's step, `RT-EXTERNAL-GATEWAY-RETIRE-UPSTREAM`).
- **D5 — the switch.** A `channel` credential is honoured only while the namespace is the active one
  (`namespace-active.json`, the "Allow agent use outside the launcher" switch): one owner-facing switch still
  means "nothing outside the launcher reaches my agents". Alternative: the credential alone suffices (pairing
  is already an explicit owner act) — owner's call.
- **D6 — where it listens.** A gateway on this machine dials `remote_gateway_listen: 127.0.0.1` (a host string;
  the lane already refuses boolean `true`), so no LAN port opens for a local bot; a remote gateway needs the
  owner to open the interface, as for a paired phone.
- **D7 — who starts and supervises it.** Not a per-user scheduled task (the row's constraint). Options: (a) the
  serve supervises declared gateways — a `gateways` list in the namespace's config (command, args, working dir),
  started after `ready`, restarted with backoff, stopped at drain, each child handed its credential on stdin and
  its log beside the serve's; (b) the owner's own service manager runs it and it reconnects with backoff while the
  serve is down. Recommendation: (b) first — hermes owns the door, not the bot — with (a) as a later slice if the
  owner wants one switch to start everything. Owner's call.

## 3. Owner questions (the ruling row)

1. A or C (B is not offered)? 2. D5: honour a channel credential only while the external switch is on? 3. D7:
serve-supervised or owner-supervised? 4. Local only for now, or remote gateways in scope?

## 4. Where it lives (under C)

`agent_runtime/serve_gateway_auth.py` (the row fields; additive, an older row reads `kind: device`);
`agent_runtime/call_authorization.py` (the channel rule, beside the tier predicate — the gate still reads the
caller, never the request); a new `agent_runtime/serve_rpc/channel.py` (D2) reusing `_runtime_chat_message`'s
admission; `hermes_cli/harness_parts/gateway_commands/` (`pair --kind channel --instance …`). Contracts
regenerate with `scripts/gen_gateway_contracts.py`.

## 5. Build rows (filed BLOCKED on the ruling; each turns READY if C is chosen)

- `RT-EXTERNAL-GATEWAY-CHANNEL-CREDENTIAL` — D1. Test: a `channel` device bound to instance X calling
  `runtime.chat.message` for Y refuses `channel_instance_not_bound`; for X is admitted; `runtime.agent.retire`
  refuses for the kind; a `device` row written before the change reads `kind: device`. Killing mutation: drop the
  bound-instance check → the Y case is admitted and reds.
- `RT-EXTERNAL-GATEWAY-CHANNEL-MESSAGE-VERB` — D2 + D3. Test (real serve, gateway lane): two
  `runtime.channel.message` calls with one `channel_key` land in ONE session of the bound instance stamped
  `source: channel:<name>`; a second key opens a second session; the session lists in the instance's chat list.
  Killing mutation: key the map by `channel_key` alone (not the device) → two gateways sharing a key collide and
  the cross-gateway case reds.
- `RT-EXTERNAL-GATEWAY-SWITCH-GATE` — D5 as ruled. Test: with `namespace-active.json` naming another namespace
  the channel hello refuses; naming this one admits. Killing mutation: skip the record read → the refusal reds.
- `RT-EXTERNAL-GATEWAY-RETIRE-UPSTREAM` — owner sitting, after the owner's first gateway answers: stop the alice
  upstream gateway, remove its logon task, delete the bot token from the eight profile `.env` files. No code.
