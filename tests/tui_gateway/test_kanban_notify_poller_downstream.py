"""Fork-owned tests moved out of ``tests/tui_gateway/test_kanban_notify_poller.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""



def test_kanban_visibility_default_does_not_dispatch_agent_turn(monkeypatch):
    import tui_gateway.server as notifications
    emitted, submitted = [], []
    monkeypatch.delenv("HERMES_BACKGROUND_AGENT_TURNS", raising=False)
    monkeypatch.setattr(notifications, "_load_cfg", lambda: {})
    monkeypatch.setattr(notifications, "_collect_kanban_notifications", lambda session: ["task done"])
    monkeypatch.setattr(notifications, "_emit", lambda *args: emitted.append(args))
    monkeypatch.setattr(notifications, "_notif_submit", lambda *args: submitted.append(args))
    session = {"_kanban_pending": ["old task"]}
    notifications._notif_poll_kanban("session", session)
    assert emitted == [("status.update", "session", {"kind": "process", "text": "task done"})]
    assert not submitted
    assert "_kanban_pending" not in session
