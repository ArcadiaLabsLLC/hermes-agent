"""Bounded, coalesced delivery off the foreground turn and settings writers."""
from threading import Condition, Thread

__layer__ = "lanes"


class SuggestionNotifications:
    def __init__(self, deliver):
        self.deliver = deliver
        self.condition = Condition()
        self.pending = {}
        self.closed = False
        self.worker = None

    def put(self, subscription, method, payload):
        with self.condition:
            if self.closed:
                return
            # At most 128 live subscriptions; detached final frames can only
            # displace older frames for the same subscription. Never grow on a
            # stalled connection or block a foreground turn.
            if subscription.id not in self.pending and len(self.pending) >= 128:
                self.pending.pop(next(iter(self.pending)))
            self.pending[subscription.id] = (subscription, method, dict(payload))
            if self.worker is None:
                self.worker = Thread(target=self._run, name="console-suggestion-push", daemon=True)
                self.worker.start()
            self.condition.notify()

    def _run(self):
        while True:
            with self.condition:
                while not self.pending and not self.closed:
                    self.condition.wait()
                if self.closed:
                    return
                item = self.pending.pop(next(iter(self.pending)))
            self.deliver(*item)

    def close(self):
        with self.condition:
            self.closed = True
            self.pending.clear()
            self.condition.notify_all()
