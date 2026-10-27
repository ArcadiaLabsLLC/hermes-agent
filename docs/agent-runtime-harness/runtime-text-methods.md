# `runtime.text.summarize` — method contract

One-shot text work through the **user's own model**: the Launcher hands Hermes a window of
conversation lines and gets bullets back. Registered by `agent_runtime/serve_rpc/text.py`; the
work is `agent_runtime/text_summary.py`. Frames, error codes and the manifest follow
[03 — transport and wire](03-transport-and-wire.md). Plan: launcher
`docs/messaging/planned/DIGEST_SUMMARIES_ON_LAUNCHER_2026-10-27.md` S0 (hermes row
`RT-AUX-SUMMARIZE`).

Every success result carries `contract: 1`. Adding the method grows the manifest set without
moving `RPC_CONTRACT_VERSION`.

## Which model answers

Each task is an auxiliary slot the harness plugin registers
(`text_summary.register_summary_tasks`, called from `plugins/eternia-harness/__init__.py::register`)
with `inherit_from: compression`. So a summary goes wherever the user's compression goes: their
signed-in provider, or the local llama model when that is their main model, until the user pins
`auxiliary.message_digest` to something else. The call runs through the plugin LLM facade
(`ctx.llm.complete`, upstream `agent/plugin_llm.py`) inside the head home's scope, so a persona's
projected model never answers it. The Launcher never names a model and never holds a key.

## The method

| method | tier | params | result |
|---|---|---|---|
| `runtime.text.summarize` | console | `task`, `lines`, `max_bullets?`, `locale?` | `{contract, text, model, provider, truncated}` |

- `task` — a row of `SUMMARY_TASKS`; today only `message_digest`.
- `lines` — `[{at, speaker, text}]`, oldest first, 1 to 2 000 entries. `speaker` and `text` are
  non-empty strings (at most 120 and 8 000 characters); `at` is an optional display timestamp
  (at most 64). Whitespace inside a line is collapsed.
- `max_bullets` — integer 1–10, default 6. The prompt asks for at most that many, and at least 3
  when there is enough to say.
- `locale` — a BCP 47 tag (`en`, `pt-BR`), default `en`; the summary is written in it.
- `text` — the model's bullets, `- ` per line, stripped. `model` / `provider` name who answered.
- `truncated` — `true` when the rendered transcript was over **60 000 characters** (the backend's
  own cap) and the OLDEST lines were dropped to fit. The newest line alone over the cap is
  `lines_too_long`.

The prompt is ported from the backend's `search/summaries.py::_summarize_with_llm` (3–6 bullets;
decisions, unanswered questions, action items) and tells the model the transcript is data, not
instructions. Temperature 0.2, at most 600 output tokens. Nothing is stored.

## Refusals

`data.reason` is the branch; the code is the family.

| code | reasons |
|---|---|
| `-32602` invalid params | `task_unknown`, `lines_empty`, `lines_too_many`, `line_invalid`, `line_text_invalid`, `line_text_too_long`, `line_speaker_invalid`, `line_speaker_too_long`, `line_at_invalid`, `line_at_too_long`, `lines_too_long`, `max_bullets_invalid`, `locale_invalid` |
| `-32000` handler failed | `model_unavailable` (no model is set up: the Launcher's "set up a model" state), `plugin_unavailable` (the harness plugin did not load), `empty_summary`, `handler_failed` (+ `error_class` only; provider text never rides the wire) |

The reply is deferred onto the transport's worker lane when it has one; a direct call answers
inline.
