"""Fork-owned tests moved out of ``tests/agent/test_subagent_progress.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""



class TestNativeReasoningEmit:
    """Tests for the fork-addition thinking emits in the conversation loop
    (trace-visibility G3 + the reply-echo suppression fix). Mirrors the exact
    combined code path in ``agent/conversation_loop.py``: native reasoning is
    extracted first and OWNS the turn's thinking row; the legacy reply-echo
    emit fires only when the provider surfaced no native reasoning. Same
    simulation idiom :class:`TestThinkingCallback` uses for its sibling block."""

    def _simulate_thinking_emits(
        self, native_reasoning, content, callback, delegate_depth=0
    ):
        """Faithful copy of the conversation-loop thinking-emit path.

        ``native_reasoning`` stands in for ``agent._extract_reasoning(...)``;
        ``content`` for ``assistant_message.content``.
        """
        import re
        _native = ""
        if callback and delegate_depth == 0:
            _native = native_reasoning.strip() if native_reasoning else ""
        if content and callback:
            _think_text = re.sub(
                r'</?(?:REASONING_SCRATCHPAD|think|reasoning)>', '',
                content.strip(),
            ).strip()
            first_line = _think_text.split('\n')[0][:80] if _think_text else ""
            if first_line and delegate_depth > 0:
                try:
                    callback("_thinking", first_line)
                except Exception:
                    pass
            elif _think_text and not _native:
                try:
                    callback("reasoning.available", "_thinking", _think_text[:500], None)
                except Exception:
                    pass
        if _native:
            try:
                callback("reasoning.available", "_thinking", _native[:500], None)
            except Exception:
                pass

    def test_native_reasoning_owns_the_row_echo_suppressed(self):
        # THE live-run regression (2026-07-17 retest): native reasoning and the
        # reply both present -> exactly ONE thinking emit, carrying the native
        # text; the reply echo must NOT also surface as a near-duplicate row
        # (whitespace-collapse + the 500-char cap defeat the projection's
        # byte-equal dedup, so suppression must happen at the emit).
        calls = []
        self._simulate_thinking_emits(
            "Let me plan the fan-out: one bounded order per teammate, then summarize.",
            "Dispatched to all three: backend_dev, dev, and qa.",
            lambda *args: calls.append(args),
        )
        assert len(calls) == 1
        assert calls[0][0] == "reasoning.available"
        assert calls[0][1] == "_thinking"
        assert "plan the fan-out" in calls[0][2]
        assert "Dispatched to all three" not in calls[0][2]

    def test_native_reasoning_fires_on_empty_content_turn(self):
        # Reasoning-only codex turn: content is empty, native reasoning present.
        # This is the case the pre-G3 code dropped (emit was inside the content
        # gate).
        calls = []
        self._simulate_thinking_emits(
            "Thinking through the plan; no visible reply text yet.",
            "",
            lambda *args: calls.append(args),
        )
        assert len(calls) == 1
        assert "Thinking through the plan" in calls[0][2]

    def test_native_reasoning_truncated_to_500(self):
        calls = []
        self._simulate_thinking_emits(
            "z" * 900, "a reply", lambda *args: calls.append(args)
        )
        assert len(calls) == 1
        assert len(calls[0][2]) == 500

    def test_fused_reasoning_emits_exactly_once(self):
        # A provider that inlines reasoning into content: native == content.
        # The native emit carries it and the echo stays suppressed — one row,
        # not zero (the retired != guard would have emitted NOTHING on this
        # shape once echo suppression landed).
        text = "This is the whole message, reasoning and reply fused together."
        calls = []
        self._simulate_thinking_emits(
            text, text, lambda *args: calls.append(args)
        )
        assert len(calls) == 1
        assert calls[0][0] == "reasoning.available"
        assert calls[0][2] == text

    def test_subagent_keeps_first_line_relay_only(self):
        # depth > 0 keeps its existing first-line _thinking relay untouched and
        # never emits reasoning.available.
        calls = []
        self._simulate_thinking_emits(
            "child reasoning", "child reply",
            lambda *args: calls.append(args), delegate_depth=1,
        )
        assert len(calls) == 1
        assert calls[0][0] == "_thinking"
        assert calls[0][1] == "child reply"

    def test_echo_fallback_when_native_absent(self):
        # No native reasoning parsed: the legacy reply-echo stand-in still
        # fires so providers without parsed reasoning keep a thinking row.
        calls = []
        self._simulate_thinking_emits(
            None, "just a reply", lambda *args: calls.append(args)
        )
        assert len(calls) == 1
        assert calls[0][0] == "reasoning.available"
        assert calls[0][2] == "just a reply"
