"""Serve-owned suggestion lifecycle: bounded work, scoped push and stale-result fences."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import logging
import sqlite3
from pathlib import Path
from threading import Condition, Thread
import time
from uuid import uuid4

from agent_runtime.call_authorization import authorize_call, TIER_CONSOLE
from agent_runtime.operator_conversation import validate_operator_conversation
from agent_runtime.persona_chat_history.suggestion_context import suggestion_context
from .generation import generate_suggestion
from .settings import SuggestionRefused, SuggestionSettings, suggestion_home
from .store import SuggestionStore, attempt_key
from .notifications import SuggestionNotifications

__layer__ = "lanes"
logger = logging.getLogger(__name__)
SETTINGS_PREFIX = "runtime.console_suggestions.settings"
CHAT_PREFIX = "runtime.operator.conversation.suggestions"
IDENTITY_KEYS = ("install_id", "workspace_id", "persona_id", "persona_instance_id", "session_id", "client_scope")


def suggestion_failure_reason(exc):
    """Classify public exception facts, never parse or return provider text."""
    from agent.auxiliary_unavailable import AuxiliaryClientUnavailable
    from httpx import TimeoutException

    classifiers = {
        SuggestionRefused: lambda error: error.reason,
        AuxiliaryClientUnavailable: lambda error: "auth",
        sqlite3.Error: lambda error: "storage",
    }
    for kind, classify in classifiers.items():
        if isinstance(exc, kind):
            return classify(exc)
    reason = {401: "auth", 403: "auth", 429: "rate_limit"}.get(getattr(exc, "status_code", None))
    if reason:
        return reason
    cause = exc
    for _ in range(4):
        if isinstance(cause, (TimeoutError, TimeoutException)):
            return "timeout"
        cause = getattr(cause, "__cause__", None)
    return "provider"


@dataclass
class Subscription:
    id: str
    context: object
    subject: dict | None
    seq: int = 0


class ConsoleSuggestions:
    def __init__(self, home: Path, *, context_reader=suggestion_context, generator=generate_suggestion, clock=time.time, observe=None):
        self.home = Path(home)
        self.settings = SuggestionSettings(self.home)
        self.context_reader = context_reader
        self.generator = generator
        self.clock = clock
        self.boot = uuid4().hex
        self.condition = Condition()
        self.subscriptions: dict[str, Subscription] = {}
        self.pending: dict[str, tuple[dict, float]] = {}
        self.running: set[str] = set()
        self.states: dict[str, dict] = {}
        self.last_dispatch: dict[str, float] = {}
        self.policy: dict | None = None
        self.pool = None
        self.scheduler = None
        self.closed = False
        self.store = SuggestionStore(self.home / "state" / "console_suggestions.sqlite3", clock=clock)
        self.notifications = SuggestionNotifications(self._deliver)
        self.observe = observe
        self.cancel_observation = None

    @staticmethod
    def key(subject):
        return json.dumps(subject, sort_keys=True)

    def settings_read(self):
        with self.condition:
            current = self.settings.read()
            current["policy_epoch"] = self.boot + ":" + current["settings_revision"]
            changed = self.policy is not None and self.policy != current
            self.policy = current
            if changed:
                self.pending.clear()
                self.states.clear()
            if changed:
                self._notify_settings(current)
                if not current["enabled"]:
                    self._disable_chats(current)
                else:
                    self.changed()
            if current["enabled"] and self._ensure_observer():
                self.changed()
            return current

    def settings_write(self, params):
        self.settings.write(params)
        return self.settings_read()

    def subscribe(self, context, subject=None):
        if context.emit is None:
            raise SuggestionRefused("push_unavailable")
        policy = self.settings_read()
        if subject is not None:
            if not policy["enabled"]:
                return self._state(subject, "disabled", policy)
            with suggestion_home(self.home):
                validate_operator_conversation(subject)
        connection = context.connection_key
        with self.condition:
            if subject is not None and self.policy["policy_epoch"] != policy["policy_epoch"]:
                return self._state(subject, "disabled", self.policy)
            same = next((sub for sub in self.subscriptions.values()
                         if sub.context.connection_key == connection and sub.subject == subject), None)
            if same is None:
                family = [sub for sub in self.subscriptions.values() if (sub.subject is None) == (subject is None)]
                if len(family) >= 64 or (subject is not None and sum(sub.context.connection_key == connection for sub in family) >= 8):
                    raise SuggestionRefused("subscription_limit")
                same = Subscription(uuid4().hex, context, subject)
                self.subscriptions[same.id] = same
        result = policy if subject is None else self.read(subject)
        with self.condition:
            baseline = {**result, "subscription_id": same.id, "seq": 0}
        if subject is not None:
            with self.condition:
                self._ensure_observer()
            self._enqueue(subject)
        return baseline

    def _ensure_observer(self):
        if (not self.closed and self.observe is not None and self.cancel_observation is None
                and any(sub.subject is not None for sub in self.subscriptions.values())):
            self.cancel_observation = self.observe(self.on_frame, self.observation_lost)
            return True
        return False

    def observation_lost(self):
        """The existing liveness metadata tick reattaches a dropped shared sink."""
        with self.condition:
            if self.cancel_observation is not None:
                cancel, self.cancel_observation = self.cancel_observation, None
                cancel()
            self.pending.clear()
            for sub in list(self.subscriptions.values()):
                if sub.subject is not None:
                    self._publish(sub.subject, self._state(sub.subject, "none", self.policy, reason="source_unavailable"))

    def unsubscribe(self, context, subscription_id):
        with self.condition:
            sub = self.subscriptions.get(subscription_id)
            if sub is not None and sub.context.connection_key != context.connection_key:
                raise SuggestionRefused("foreign_subscription")
            self.subscriptions.pop(subscription_id, None)
            self._trim_unobserved()
        return {"contract": 1, "released": sub is not None}

    def release(self, connection):
        with self.condition:
            self.subscriptions = {key: sub for key, sub in self.subscriptions.items()
                                  if sub.context.connection_key != connection}
            self._trim_unobserved()

    def _trim_unobserved(self):
        observed = {self.key(sub.subject) for sub in self.subscriptions.values() if sub.subject is not None}
        if not observed and self.cancel_observation is not None:
            cancel, self.cancel_observation = self.cancel_observation, None
            cancel()
        for mapping in (self.states, self.pending, self.last_dispatch):
            for key in set(mapping) - observed - self.running:
                mapping.pop(key, None)

    def read(self, subject):
        policy = self.settings_read()
        if not policy["enabled"]:
            return self._state(subject, "disabled", policy)
        with suggestion_home(self.home):
            validate_operator_conversation(subject)
        with self.condition:
            state = dict(self.states.get(self.key(subject), self._state(subject, "idle", policy)))
        if state.get("source_revision"):
            with suggestion_home(self.home):
                fresh = self.context_reader(subject, policy["max_context_messages"])
            if fresh.get("source_revision") != state["source_revision"]:
                return self._state(subject, "none", policy, reason="source_changed")
        return state

    def dismiss(self, subject, params):
        state = self.read(subject)
        key = state.get("attempt_key")
        if key is None or state.get("entry_id") != params.get("entry_id"):
            raise SuggestionRefused("stale_revision")
        self.store.dismiss(key, params["entry_id"], params.get("expected_revision"))
        updated = {**state, "state": "none", "reason": "dismissed"}
        updated.pop("text", None)
        self._publish(subject, updated)
        return updated

    def changed(self, session_id=None):
        """A completed native operation invalidates visible subjects; no history on the caller."""
        with self.condition:
            subjects = {self.key(sub.subject): sub.subject for sub in self.subscriptions.values()
                        if sub.subject is not None and (session_id is None or sub.subject["session_id"] == session_id)}
        for subject in subjects.values():
            self._publish(subject, self._state(subject, "none", self.policy, reason="source_changed"))
            self._enqueue(subject)

    def on_frame(self, frame):
        """Observe the existing shared stream; never tail events independently."""
        kind = frame.get("type")
        relevant = {
            "hydrate": lambda: True,
            "persona_chat_turn": lambda: True,
            "patch": lambda: any(str(row.get("entity", "")).startswith("persona_chat") for row in frame.get("patches", [])),
            "delta": lambda: any(str(row.get("event", {}).get("type", "")).startswith(
                ("persona_chat.", "persona_chat_turn.", "realm.sync.")) for row in frame.get("events", [])),
        }.get(kind)
        if relevant is not None and relevant():
            self.changed(frame.get("root_chat_session_id"))

    def turn_changed(self, argv, *, started):
        if "--session-id" not in argv:
            return
        index = argv.index("--session-id") + 1
        if index >= len(argv):
            return
        with self.condition:
            subjects = {self.key(sub.subject): sub.subject for sub in self.subscriptions.values()
                        if sub.subject is not None and sub.subject["session_id"] == argv[index]}
        for subject in subjects.values():
            if started:
                self._publish(subject, self._state(subject, "none", self.policy, reason="turn_active"))
            else:
                self._enqueue(subject)

    def _enqueue(self, subject):
        with self.condition:
            if self.closed or not self.policy or not self.policy["enabled"]:
                return
            key = self.key(subject)
            if key not in self.pending and len(self.pending) >= 32:
                self._publish(subject, self._state(subject, "none", self.policy, reason="capacity_limited"))
                return
            due = self.last_dispatch.get(key, 0) + self.policy["cooldown_seconds"]
            self.pending[key] = (subject, due)
            if self.pool is None:
                self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="console-suggestion")
                self.scheduler = Thread(target=self._schedule, name="console-suggestion-scheduler", daemon=True)
                self.scheduler.start()
            self.condition.notify_all()

    def _schedule(self):
        while True:
            with self.condition:
                if self.closed:
                    return
                eligible = [(key, value) for key, value in self.pending.items() if key not in self.running]
                if not eligible or len(self.running) >= 2:
                    self.condition.wait()
                    continue
                key, (subject, due) = min(eligible, key=lambda item: item[1][1])
                delay = due - self.clock()
                if delay > 0:
                    self.condition.wait(min(delay, 60))
                    continue
                self.pending.pop(key)
                self.running.add(key)
                self.pool.submit(self._work, subject)

    def _work(self, subject):
        key = self.key(subject)
        attempt = None
        owned = False
        base = None
        try:
            policy = self.settings_read()
            if not policy["enabled"] or not self._observed(subject):
                return
            with suggestion_home(self.home):
                source = self.context_reader(subject, policy["max_context_messages"])
            if source.get("reason"):
                self._publish(subject, self._state(subject, "none", policy, reason=source["reason"]))
                return
            attempt = attempt_key(subject, source, policy["settings_revision"])
            claimed = self.store.claim(attempt, subject, source["source_time"])
            base = {**self._state(subject, "generating", policy), "source_turn_id": source["source_turn_id"],
                    "source_revision": source["source_revision"], "attempt_key": attempt}
            if claimed == "capacity_limited":
                self._publish(subject, {**base, "state": "none", "reason": claimed})
                return
            if claimed == "existing":
                self._publish(subject, {**base, **(self.store.read(attempt) or {"state": "none"})})
                return
            owned = True
            with self.condition:
                current = self.settings_read()
                if (not current["enabled"] or current["policy_epoch"] != policy["policy_epoch"]
                        or not self._observed(subject)):
                    self.store.finish(attempt)
                    return
                self.last_dispatch[key] = self.clock()
            self._publish(subject, base)
            # Synchronous facade: UI cancellation invalidates publication but never
            # releases an outstanding provider slot early or closes a shared client.
            with suggestion_home(self.home):
                generated = self.generator(source["messages"])
                fresh = self.context_reader(subject, policy["max_context_messages"])
            current = self.settings_read()
            valid = (current["enabled"] and current["policy_epoch"] == policy["policy_epoch"]
                     and fresh.get("source_revision") == source["source_revision"] and self._observed(subject))
            self.store.finish(attempt, text=generated.get("text") if valid else None,
                              usage={"provider": generated.get("provider"), "model": generated.get("model"),
                                     **generated.get("usage", {})})
            if valid:
                self._publish(subject, {**base, **self.store.read(attempt)})
        except Exception as exc:  # health: allow BLE001 -- provider SDK boundary; log only class/reason, never provider credentials or prompts
            reason = suggestion_failure_reason(exc)
            logger.info("console_suggestion_failed reason=%s class=%s", reason, type(exc).__name__)
            if owned:
                try:
                    self.store.finish(attempt, reason=reason)
                    self.settings_read()
                    with suggestion_home(self.home):
                        fresh = self.context_reader(subject, policy["max_context_messages"])
                    if fresh.get("source_revision") == source["source_revision"]:
                        self._publish(subject, {**base, **self.store.read(attempt)})
                except Exception:  # health: allow BLE001 -- failed receipt storage must not escape the optional worker or expose source text
                    logger.info("console_suggestion_receipt_unavailable")
        finally:
            with self.condition:
                self.running.discard(key)
                self._trim_unobserved()
                self.condition.notify_all()

    def _observed(self, subject):
        with self.condition:
            return not self.closed and any(sub.subject == subject for sub in self.subscriptions.values())

    @staticmethod
    def _state(subject, state, policy, **extra):
        return {"contract": 1, **subject, "state": state, "policy_epoch": policy["policy_epoch"], **extra}

    def _publish(self, subject, state):
        with self.condition:
            if (self.closed or not self.policy["enabled"] or state["policy_epoch"] != self.policy["policy_epoch"]
                    or not self._observed(subject)):
                return
            self.states[self.key(subject)] = state
            targets = [sub for sub in self.subscriptions.values() if sub.subject == subject]
        self._emit(targets, CHAT_PREFIX + ".changed", state)

    def _notify_settings(self, policy):
        with self.condition:
            targets = [sub for sub in self.subscriptions.values() if sub.subject is None]
        self._emit(targets, SETTINGS_PREFIX + ".changed", policy)

    def _disable_chats(self, policy):
        with self.condition:
            targets = [sub for sub in self.subscriptions.values() if sub.subject is not None]
            for sub in targets:
                self.subscriptions.pop(sub.id, None)
            self._trim_unobserved()
        for sub in targets:
            self._emit([sub], CHAT_PREFIX + ".changed", self._state(sub.subject, "disabled", policy))

    def _emit(self, targets, method, payload):
        for sub in targets:
            self.notifications.put(sub, method, payload)

    def _deliver(self, sub, method, payload):
        if not authorize_call(TIER_CONSOLE, sub.context.caller, method=method.removesuffix(".changed") + ".subscribe").ok:
            self.release(sub.context.connection_key)
            return
        with self.condition:
            if self.closed or payload["policy_epoch"] != self.policy["policy_epoch"]:
                return
            if sub.id not in self.subscriptions and payload.get("state") != "disabled":
                return
            sub.seq += 1
            frame = {**payload, "subscription_id": sub.id, "seq": sub.seq}
        frame.pop("attempt_key", None)
        try:
            sub.context.push(method, frame)
        except Exception:  # health: allow BLE001 -- arbitrary connection sink; release observer without leaking payloads or delaying a turn
            self.release(sub.context.connection_key)

    def close(self):
        self.notifications.close()
        with self.condition:
            self.closed = True
            self.subscriptions.clear()
            self.pending.clear()
            self._trim_unobserved()
            self.condition.notify_all()
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)
