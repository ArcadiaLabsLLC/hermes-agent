"""Messaging platforms — the fork's headless persona gateway, Telegram first (p10-messaging).

Plan ``docs/agent-runtime-harness/planned/p10-messaging-2026-10-19.md``. Fork-owned end to end: no
upstream platform adapter is wrapped (ADR 0015 keeps them unused), the transport is the raw Bot API
over ``httpx``. Off by default: the harness setting ``messaging_enabled`` is false, and both bundle
manifests switch this package off (``packaging.switched_off_modules``).

models (models): ``Platform``, ``Reason``, ``MessagingRefused`` — the closed vocabularies;
bindings (stores): ``Binding`` / ``BindingStore`` — a platform chat POINTS AT a persona instance, never a session;
operators (stores): ``Operator`` / ``OperatorStore`` — who may talk; fail closed;
credentials (stores): ``bot_token`` / ``set_token`` / ``clear_token`` — the bot token behind the host-store seam;
rpc (lanes): ``runtime.messaging.status|binding.*|operator.*|credential.*``;
chunks (models): ``chunk(text, limit)`` — a reply split at a platform's message limit;
transport (models): ``Transport`` — the protocol every platform transport implements, and its values;
telegram_api (lanes): ``TelegramTransport`` — Bot API long polling over ``httpx``, backoff as a table;
bridge (lanes): ``MessagingBridge`` — inbound → a queued turn of the bound instance → the settle's reply;
approvals (lanes): ``ApprovalCards`` — an approval on a bound root as a platform card, answered via ``respond_operator_approval``.
"""

__layer__ = "models"
__all__: list[str] = []
