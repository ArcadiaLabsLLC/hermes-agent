# R007 review correction — heartbeat / terminal race

Base: accepted Wave1 518b14aa9cbc28208008a3373f368c02515665d7 on grind/sol-runtime-20261007.

Parent review correctly found that ToolHeartbeat.stop only sets an Event: a beat already running could emit turn.progress or tool.progress after the real emitter.finish emitted turn.end. The previous manually joined heartbeat test did not prove the claimed terminal boundary.

Repair: inside _ChatProtocolV2Emitter._emit_chat_frame's existing emission lock, drop those two progress frame types once finish has marked the emitter finished. No heartbeat join or extra lock is added. A frame already inside the writer can finish before the terminal writer acquires the lock; a blocked/stale beat cannot emit afterwards. Existing finish segment.end and turn.end frames remain permitted. Other frame types and the transport are unchanged.

Deterministic focused proof parametrizes the blocked in-flight frame (turn.progress / tool.progress), starts a real beat on a controlled thread, calls real finish while the beat is blocked, then releases it. It asserts the heartbeat stop event, segment.end before one turn.end, no thread/error leak and no later progress. Both cases fail on the original code at the final late-progress assertion (runtime-heartbeat-finish-red.log). With the emission fence, the entire named test_turn_liveness_heartbeat.py file passes: 3 tests in 1.30s (runtime-heartbeat-finish-green.log). Focused Ruff on the two touched files passes. No full suite or main write.

This closes the review correction to the original R007 proof; it is not new evidence that the original manual join test was sufficient. Wave1 R039 remains accepted; R011 remains pending local design follow-on. No other claims opened. Old QA patch, Job2 tree and all prior evidence preserved.
