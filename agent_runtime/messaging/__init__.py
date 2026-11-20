"""Messaging platforms — the fork's headless persona gateway, Telegram first (p10-messaging).

Plan ``docs/agent-runtime-harness/planned/p10-messaging-2026-10-19.md``. The persona system, stores, bridge
and approval cards are the fork's; the platform connection is upstream's own adapter used as a plain pipe
behind ``upstream_adapter_transport`` (RT-MESSAGING-RETIRE-FORK-TELEGRAM retired the fork's own httpx
Telegram transport after the opt-in trial). Off by default: the harness setting ``messaging_enabled`` is false, and both bundle
manifests switch this package off (``packaging.switched_off_modules``).

models (models): ``Platform``, ``Reason``, ``MessagingRefused`` — the closed vocabularies;
bindings (stores): ``Binding`` / ``BindingStore`` — a platform chat POINTS AT a persona instance, never a session;
operators (stores): ``Operator`` / ``OperatorStore`` — who may talk; fail closed;
credentials (stores): ``bot_token`` / ``set_token`` / ``clear_token`` — the bot token behind the host-store seam;
rpc (lanes): ``runtime.messaging.status|binding.*|operator.*|credential.*``;
transport (models): ``Transport`` — the protocol the bridge and approval cards talk to, and its values;
upstream_adapter_transport (lanes): ``TelegramUpstreamAdapterTransport`` — upstream's adapter behind ``Transport``,
the fork's sender gate at its intake;
bridge (lanes): ``MessagingBridge`` — inbound → a queued turn of the bound instance → the settle's reply;
approvals (lanes): ``ApprovalCards`` — an approval on a bound root as a platform card, answered via ``respond_operator_approval``.
serve_lane (lanes): ``start_messaging_bridge`` — the bridge as a serve lane: setting + token + drain, reconciled per tick.
"""

__layer__ = "models"
__all__: list[str] = []
