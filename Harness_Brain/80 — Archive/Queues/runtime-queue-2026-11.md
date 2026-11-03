---
type: queue-archive
queue: runtime-queue.md
program: mission-control
month: 2026-11
---

Closed rows of `runtime-queue.md` for 2026-11; appended by the close commits, never edited.

- **`RT-NEXT-PROMPT-MODES` — Add Off / Manual / Auto policy and an exact-conversation one-shot generation request, with the paired Eternia Intelligence composer action** · `agent_runtime/console_suggestions/settings.py` · `agent_runtime/console_suggestions/service.py` · `EterniaLauncher/lib/features/harness/widgets/harness_suggestions_settings.dart` · RULED 2026-11-03: owner approved Off / Manual / Auto and the right-side Intelligence button; preserve default Off, map existing On to Auto, Manual generates only on click and retains draft review before sending · DONE 2026-11-03 4828f0577617b66405cb71df78ca233c7aa1b5c7 · result: Off / Manual / Auto runtime and paired Eternia UI landed (client 35e860a244); default Off, legacy On to Auto, exact one-shot Manual request and guarded draft review; focused tests, pictures, mutation proofs and paired native RPC passed; existing broader qualification remains in its own queue
