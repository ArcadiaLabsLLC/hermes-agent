from tui_gateway import event_replay as replay


def emit(sid, text="word"):
    frame = {"method": "event", "params": {"session_id": sid,
             "type": "message.delta", "payload": {"text": text}}}
    replay._stamp_event(frame)
    return frame["params"]["seq"]


def test_cache_eviction_does_not_reset_live_session_identity(monkeypatch):
    replay.reset_replay_state()
    monkeypatch.setattr(replay, "_REPLAY_SESSIONS_MAX", 2)
    before = [emit("active") for _ in range(3)][-1]
    epoch = replay.replay_epoch()
    emit("other-a")
    emit("other-b")
    assert replay.latest_seq("active") == before
    assert replay.is_truncated("active", 0)
    assert emit("active") == before + 1
    assert replay.replay_epoch() == epoch
    assert replay.events_since("active", before)[0]["seq"] == before + 1
    replay.reset_replay_state()
