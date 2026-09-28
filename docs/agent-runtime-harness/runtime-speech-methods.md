# `runtime.speech.*` and `runtime.admission.*` — method contract

Bundled Hermes loads the speech models the Launcher downloads and runs speech
inference on the desktop; the Launcher samples the voice and owns the speech
port and UI (launcher `docs/embedded_hermes/planned/ARCHITECTURE_2026-09-28.md`
§5, §5.1; plan D3 items 1–2). Registered by `agent_runtime/serve_rpc/speech.py`
and `agent_runtime/serve_rpc/admission.py`; the work is
`agent_runtime/speech_service.py` and `agent_runtime/model_admission.py`.
Frames, error codes and the manifest follow
[03 — transport and wire](03-transport-and-wire.md).

Every success result carries `contract: 1`. Adding these methods grows the
manifest set without moving `RPC_CONTRACT_VERSION`.

## Engines — enabled, not reimplemented

| Step | Upstream code used |
|---|---|
| STT load | `tools/transcription_local.py::_load_local_whisper_model` (via `_upstream_doors.whisper_load_model`), `device="cpu"`, `compute_type="int8"` |
| STT decode | `build_local_transcribe_kwargs` (VAD, confidence gate, `language: en` unless `stt.language` says otherwise) and `_join_confident_segments` |
| TTS load | `tools/tts_tool_local.py::_load_piper_voice_for_config` (the same LRU slot the `speak` tool reads); unload is `release_tts_provider("piper")` |
| TTS synth | `PiperVoice.synthesize` (one chunk per sentence) |

Versions measured: faster-whisper 1.2.1, ctranslate2 4.8.2, piper-tts 1.8.0,
onnxruntime 1.30.0, numpy 2.5.3 (the `pyproject.toml` pins).

## Models: explicit local paths, never a download

A model is named by an **absolute path**, or by a bare name under `models_dir`:

- STT: a faster-whisper (CTranslate2) **directory** holding `model.bin`,
  `config.json`, `tokenizer.json` and `vocabulary.txt` (or `.json`).
  faster-whisper never resolves a directory against the Hub.
- TTS: a Piper voice `<name>.onnx` with its `<name>.onnx.json` beside it.
  Upstream's resolver returns an existing `.onnx` before its download branch.

With no param, the existing config keys are read: `stt.local.model` and
`tts.piper.voice` — used only when they hold an absolute path. A bare Hub name
there (`base`, `en_US-lessac-medium`) reads `model_not_local`; it is never
fetched.

Validation runs before any loader, so a missing or partial model reads
`unavailable` with a typed reason and nothing is fetched. The bundled profile
(`agent_runtime/bundle_profiles/bundled-desktop.yaml`) also sets
`HF_HUB_OFFLINE=1`; Piper's voice download (`python -m piper.download_voices`,
not `huggingface_hub`) now honours that switch too, through a two-line fork seam
in `tools/tts_tool_local.py::_resolve_piper_voice_path`.

**CPU default** (owner ruling 1: mid-range PC, no dedicated GPU): `int8` on
CPU, one Whisper-family English model and one Piper voice. Measured below:
`faster-whisper-tiny.en` meets the ≤ ~1 s budgets on the measurement machine;
`faster-whisper-base.en` is more accurate and misses them. Voice:
`en_US-lessac-medium`. The model the Launcher's catalog lists is the product
choice; the service loads whichever directory it is given.

## Methods

| method | tier | params |
|---|---|---|
| `runtime.speech.status` | read | optional `models_dir`, `stt_model`, `tts_voice` (inspect those instead of config) |
| `runtime.speech.load` | console | `models_dir?`, `stt_model?`, `tts_voice?`, `which?` (`stt` \| `tts` \| `both`, default `both`) |
| `runtime.speech.unload` | console | `which?` |
| `runtime.speech.recognize.begin` | console | `sample_rate?` (16000), `encoding?` (`pcm_s16le`), `language?` (`en`) |
| `runtime.speech.recognize.push` | console | `stream_id`, `seq` (0, 1, 2 …), `audio` (base64 PCM) |
| `runtime.speech.recognize.end` | console | `stream_id` |
| `runtime.speech.recognize.cancel` | console | `stream_id` |
| `runtime.speech.synthesize` | console | `text` (1–4000 chars) |
| `runtime.admission.status` | read | — |
| `runtime.admission.reserve` | console | `holder`, `kind` (`llm` \| `stt` \| `tts`, default `llm`), `resource` (`vram` \| `ram`), `bytes`, `lease_seconds?` (default 120, max 3600) |
| `runtime.admission.release` | console | `holder` |

Tiers follow `runtime.local_llama.*`: `status` reads, every verb that loads a
model or spends inference is `console`. Unknown params are ignored.

`load`, `recognize.end` and `synthesize` answer on the transport's worker lane
when it has one (`RpcContext.spawn_reply`); the reply arrives on the same `id`.

## Results

**status** —
`{contract, stt: SLOT, tts: SLOT, streams, admission: ADMISSION}` where SLOT is

```
{state, reason, model_path, engine, reserved_bytes, unloaded_reason,
 missing?,                       # model_partial: the absent/empty/unparseable files
 disk_bytes?,                    # available
 device, compute_type, input_sample_rate, input_encoding,   # stt
 sample_rate}                    # tts (from the voice's .onnx.json)
```

| state | meaning |
|---|---|
| `unavailable` | `reason` ∈ `model_unset`, `model_not_local`, `model_missing`, `model_partial`, `engine_missing`, `load_failed` |
| `available` | files complete, engine importable, not loaded |
| `loading` | a load is running |
| `loaded` | ready; `reserved_bytes` is its admission reservation |

`unloaded_reason` is the last way a model left memory: `unloaded`, `evicted`
(the admission authority needed the room), `replaced`, `closed`.

**load** — `{contract, results: {stt?, tts?}, …status}`. Each result is
`{state: "loaded" | "unavailable" | "refused" | "loading", reason, …}`; a
`refused` result carries the admission refusal's fields (below). One model
failing does not stop the other.

**recognize.begin** — `{contract, stream_id, partials, sample_rate, encoding,
max_chunk_bytes: 65536, max_seconds: 120}`. `partials` is false when the
connection has no push channel (stdio probes, tests): only the final arrives.

**recognize.push** — `{contract, stream_id, seq, audio_ms}` (total buffered).

**recognize.end** — `{contract, stream_id, text, audio_ms, partials,
adopted_partial, final_latency_ms}`. `adopted_partial: true` means the last
partial already covered every byte and was used as the final instead of a
second pass.

**synthesize** — after the chunk events:
`{contract, synth_id, sample_rate, channels: 1, encoding: "pcm_s16le", chunks,
bytes, audio_ms, first_chunk_ms, elapsed_ms}`.

**admission.status** — `{contract, shared_memory, pools: {name:
{capacity_bytes, reserved_bytes}}, reservations: [{holder, kind, pool,
resource, bytes, owner, evictable, idle, evicting, lease_remaining_s}],
refusals, evictions}`.

**admission.reserve** — `{contract, holder, pool, bytes, capacity_bytes,
reserved_bytes, lease_seconds}`. **release** — `{contract, holder, released}`.

## Events (notifications to the caller's own connection)

| method | params |
|---|---|
| `runtime.speech.recognize.partial` | `{stream_id, index, text, audio_ms}` — a preview; the final replaces it |
| `runtime.speech.recognize.final` | the `recognize.end` result without `contract` |
| `runtime.speech.synthesize.chunk` | `{synth_id, seq, sample_rate, audio}` — `seq` from 0; the reply follows the last one |

## Audio framing — decision

**Base64 PCM inside ordinary JSON-RPC frames, no side channel** (plan D3 item 2).

- In: `pcm_s16le`, mono, 16 kHz — 32 000 B/s raw, ~42.7 KB/s as base64. The
  Launcher (the voice sampling authority) resamples before sending; other rates
  are refused (`audio_format_unsupported`). One push carries at most 64 KiB
  decoded (2 s); the Launcher sends ~100 ms.
- Out: `pcm_s16le` mono at the voice's rate (22 050 Hz for lessac-medium),
  pushed in chunks of at most 32 KiB raw.

Measured (2026-09-28, the machine below): a 100 ms input chunk is a **4 427-byte**
push frame; the largest synthesis chunk frame is **43 864 bytes**; a 3.5 s
sentence synthesizes as 5 chunk frames. That is well under anything the serve
transports carry already, so a side channel is not warranted.

## Streaming recognition

Whisper is not a streaming model: every pass re-decodes the take so far (the
last 30 s at most). The first partial runs after 300 ms of audio, later ones
after 600 ms of new audio, one pass at a time. A pass costs about the same
whatever the clip length, because whisper pads to a 30 s window. The final pass
queues behind a partial already running; `adopted_partial` skips it when that
partial covered everything.

## Latency — measured

Machine: AMD Ryzen 7 3700X (8 cores, 2019), no GPU used (`device=cpu`,
`int8`), Windows 10. Clip: a Piper-spoken English sentence ("The quick brown
fox jumps over the lazy dog near the river bank.") resampled to 16 kHz, 200 ms
of leading and 300 ms of trailing silence, ~4.0 s total, pushed in 100 ms chunks
at real time through `handle_request`, sockets blocked. Three runs each.
"First words" is the first non-empty partial after speech starts; "final" is
from `recognize.end` to its reply.

| STT model | first words | final | load | RSS |
|---|---|---|---|---|
| `faster-whisper-tiny.en` | 0.98 / 0.99 / 0.98 s | 0.48 / 0.66 / 0.52 s | 1.7 s | +101 MiB |
| `faster-whisper-base.en` | 1.94 / 1.87 / 1.74 s | 1.50 / 1.18 / 1.20 s | 1.6 s | +137 MiB |

Both transcribed the sentence correctly. One decode pass on this CPU: tiny.en
~0.4–0.5 s, base.en ~0.7–0.8 s (for a 1 s or a 4 s clip alike).

Piper `en_US-lessac-medium`: load 4.7–5.1 s (+85 MiB), first chunk 0.26–0.28 s (2.0 s on the very first run after install)
for the sentence, whole sentence (3.5 s of audio) 0.26–0.28 s warm.

## Admission — one budget for speech and LLMs

`agent_runtime/model_admission.py` is the process's one authority (§5.1):

- **Pools** come from upstream's `hermes_cli.local_runtime.hardware.probe_budget(planning=True)`:
  a discrete card gives `vram` (total minus upstream's desktop margin) and
  `ram` (60 % of physical RAM); a machine with no discrete card or with unified
  memory has one `ram` pool, and a `vram` request lands in it.
- **Reserve before load, release after unload.** The fit check and the insert
  happen under one lock; an evicted model's bytes stay counted until its evictor
  returns, so a pool is never over-admitted.
- **Over budget:** evict least-recently-used **idle** models that registered an
  evictor (speech models do; a recognizing or synthesizing one is not idle),
  else refuse `over_budget`. A failed eviction keeps its bytes and refuses.
- **Local LLMs:** `runtime.local_llama` load reserves `llm:<model_id>` with
  upstream's footprint estimate (weights + context at the requested window,
  never below the file size; `gpu_layers: 0` is `ram`, otherwise `vram`) and
  releases on unload, stop, a failed load and close. A refused load fails with
  `admission_refused`. LLM reservations are not evictable.
- **Full Hermes** (another process) reserves through `runtime.admission.*`
  with `agent_runtime/model_admission_client.py`
  (`BundledAdmissionClient.over_socket(connection).lease(...)` renews at half
  the lease). Wire holders are stored as `remote:<holder>` — they can never
  replace a local row — are never evicted, and lapse if not renewed.

Speech estimates: STT = directory size + 96 MiB, TTS = voice size × 1.5 + 64 MiB
(measured resident: base.en +137 MiB against 237 MiB reserved; lessac-medium
+85 MiB against 154 MiB reserved — estimates round up).

## Errors

`error.data.reason` is the branch point.

| code | reason | from |
|---|---|---|
| -32602 | `models_dir_invalid`, `stt_model_invalid`, `tts_voice_invalid`, `which_invalid` | `status`, `load`, `unload` |
| -32602 | `audio_format_unsupported` (+`sample_rate`, `encoding`), `language_unsupported` | `recognize.begin` |
| -32602 | `audio_invalid` | `recognize.push`: not base64, odd byte count, or over 64 KiB |
| -32602 | `text_invalid` | `synthesize` |
| -32602 | `push_channel_required` | `synthesize` on a connection with no push channel |
| -32602 | `holder_invalid`, `kind_invalid`, `resource_invalid`, `bytes_invalid`, `lease_invalid`, `owner_invalid` | `admission.reserve` / `release` |
| 4001 | `stream_not_found` | `recognize.push/end/cancel` (unknown, ended, or another connection's) |
| 4090 | `model_not_loaded` (+`model`) | `recognize.begin`, `synthesize` |
| 4090 | `too_many_streams` (+`limit`: 4) | `recognize.begin` |
| 4090 | `seq_gap` (+`expected`) | `recognize.push` |
| 4090 | `stream_too_long` (+`max_seconds`) | `recognize.push` |
| 4090 | `over_budget` (+`pool`, `requested_bytes`, `capacity_bytes`, `reserved_bytes`, `holders`) | `admission.reserve` |
| -32000 | `handler_failed` (+`method`, `error_class`) | anything else |

An untouched stream is dropped after 60 s.
