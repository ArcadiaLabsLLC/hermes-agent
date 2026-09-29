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

## Engines

| Step | Code used |
|---|---|
| STT load, Whisper | onnx-asr 0.12.0 `load_model("whisper", <dir>, quantization="int8", providers=["CPUExecutionProvider"])` (`agent_runtime/speech_stt_engines.py::load_whisper`) |
| STT decode, Whisper | `WhisperDecoder`: greedy, over onnx-asr's encoder and decoder step, per 10 s chunk; upstream's `_join_confident_segments` gate (via `_upstream_doors.whisper_confident_text`) over each chunk |
| STT load + decode, Parakeet | onnx-asr 0.12.0 `load_model("nemo-conformer-tdt", <dir>, quantization="int8", providers=["CPUExecutionProvider"])`, then `recognize` per chunk (`agent_runtime/speech_stt_engines.py`) |
| TTS load | fork `agent_runtime/speech_onnx_voice.py::load_voice` — a Piper or Kokoro voice on onnxruntime, with its phonemizer artifact; unload drops the object |
| TTS synth | the same runner, one chunk per sentence |

**TTS is the fork's own, on purpose.** The speech pack ships no GPL code (owner
ruling 2026-09-28, second sitting, item 2; launcher
`docs/embedded_hermes/planned/GPL_FREE_TTS_OPTIONS_2026-09-28.md`). Upstream's
Piper path is `piper-tts` (GPL-3.0, espeak-ng compiled in), so the bundled
service does not enable it: `speech_onnx_voice.py` runs the voice's ONNX file
the way Piper's and Kokoro's own inference code does, and
`agent_runtime/speech_phonemize.py` turns text into phonemes. Full Hermes's
`speak` tool still uses upstream's Piper when `piper-tts` is installed.

Versions measured: onnx-asr 0.12.0, onnxruntime 1.29.0, numpy 2.4.3 (the
`pyproject.toml` pins; both STT engines are the `stt-parakeet` extra, the TTS
runner is `speech-tts`). **No ctranslate2** (owner ruling 2026-09-29): Whisper
ran on faster-whisper / ctranslate2 until lane w6-hwort, which brought Intel's
OpenMP runtime (`libiomp5md.dll`) and its licence review into the pack. The
speech pack ships neither now; full Hermes keeps upstream's faster-whisper
(`stt-whisper` extra) for its own local STT.

**The STT engine is chosen by the model folder's files, never by a config
string** (`speech_stt_engines.engine_for`). A folder whose `config.json` names
`model_type: nemo-conformer-tdt`, or that holds an `encoder-model*.onnx`, is
Parakeet; anything else is read as Whisper. `status`, `load` and the admission
estimate all read that one answer, and `status.stt.engine` reports it
(`whisper-onnx` | `parakeet-tdt`). A folder of the retired faster-whisper
engine (`model.bin`) reads `model_partial`, `missing` naming the ONNX files; a
complete folder whose `config.json` `model_type` is not its engine's reads
`model_unsupported`.

**Why the Whisper decode loop is ours.** onnx-asr loads the transformers.js
export and owns the sessions, the log-mel features (numpy, `fbanks.npz`) and
the decoder step with its key/value cache. Its own `recognize` puts
`<|en|><|transcribe|>` into every prompt; an English-only (`.en`) model was
trained on `<|startoftranscript|><|notimestamps|>` alone, and with the extra
tokens tiny.en returned empty text on two of the bench's three clips.
`WhisperDecoder` runs the greedy loop with the right prompt (a multilingual
model gets the language and task tokens), reads the no-speech probability at
the start position and the mean log-probability, and hands both to upstream's
gate. faster-whisper's VAD is replaced by an energy floor: a chunk whose
loudest 20 ms frame is under −45 dBFS is not decoded (Whisper writes "you"
over silence with a confident log-probability, which upstream's AND gate keeps),
and a whole-chunk caption such as `[BLANK_AUDIO]` is no text. Decoding is
greedy for partials and finals alike (faster-whisper's final used beam 5).

Why onnx-asr and not sherpa-onnx or an own runner: it adds the least. It is a
7 MB pure-Python MIT package whose only hard requirement is numpy, running on
the onnxruntime the speech pack already carries — no native build, no TTS code,
no espeak-ng. It is given a model TYPE and an existing local directory, which
makes its resolver offline; its `huggingface_hub` branch is unreachable. The
speech pack ships only the preprocessor data the CPU path reads
(`fbanks.npz` and the resamplers to 16 kHz); the rest is `excluded_data`.

## Models: explicit local paths, never a download

A model is named by an **absolute path**, or by a bare name under `models_dir`:

- STT, Whisper: the transformers.js ONNX export, int8, **flat** in one folder:
  `config.json` (`model_type: whisper`), `vocab.json`, `added_tokens.json`,
  `encoder_model_int8.onnx`, `decoder_model_merged_int8.onnx` — from
  `onnx-community/whisper-tiny.en` @ `2575352d61be1bf7225cf8f8b268a4678025fc58`
  (41 MB) or `onnx-community/whisper-base.en` @
  `51eefc0af78b103839eda9e7e4f4186acc6517fe` (77 MB); the repos keep the two
  `.onnx` files under `onnx/`. Weights: OpenAI Whisper (MIT).
- STT, Parakeet: the int8 ONNX export of Parakeet TDT 0.6B v2
  (`istupakov/parakeet-tdt-0.6b-v2-onnx`, 661 MB): `config.json`
  (`model_type: nemo-conformer-tdt`), `vocab.txt`, `encoder-model.int8.onnx`
  and `decoder_joint-model.int8.onnx`. Weights CC-BY-4.0 (attribution).
- TTS, Piper: a voice `<name>.onnx` with its `<name>.onnx.json` beside it.
- TTS, Kokoro: `kokoro-v1.0.onnx` with `voices-v1.0.bin` beside it (preset
  `af_heart`, 24 kHz).
- TTS phonemizer: an ARTIFACT beside the voice, downloaded with it — no
  espeak-ng anywhere:

  | voice | files | what it is |
  |---|---|---|
  | Piper | `openphonemizer-en_us.onnx` + `.json` | OpenPhonemizer (BSD-3-Clause-Clear) exported to ONNX: its 274 927-word dictionary, then its transformer for any other word; espeak-style `en-us` IPA, mapped to espeak's British `en` for a voice whose `espeak.voice` is `en` (all three catalog voices) |
  | Kokoro | `misaki-en_us-g2p.onnx` + `.json` | misaki's gold + silver lexicons and its neural fallback (both Apache-2.0), plus Kokoro's phoneme vocabulary; a word the lexicon lacks goes to the fallback, never to silence |

  Both consult a product-name lexicon first (Eternia, Hermes, Arcadia) and
  spell digits and clock times as words (the pack ships no `num2words`). The
  artifacts are made by `scripts/phonemizer_openphonemizer_onnx.py` and
  `scripts/phonemizer_misaki_g2p_onnx.py`; neither needs torch at runtime. A
  voice without its artifact reads `unavailable`, reason `phonemizer_missing`,
  `missing` naming the absent files — checked BEFORE the loader. A Piper voice
  with `phoneme_type: "text"` needs none.

**No PyAV, no faster-whisper** (bundled speech pack). A voice-note FILE —
upstream's `_transcribe_local`, which hands faster-whisper a path — has no
decode path in the bundle: faster-whisper is not installed there, so upstream's
own "not installed" answer applies. (`agent_runtime/speech_decode.py`'s PyAV
placeholder served the faster-whisper pack; retiring it is a runtime-queue row.)

With no param, the existing config keys are read: `stt.local.model` and
`tts.piper.voice` — used only when they hold an absolute path. A bare Hub name
there (`base`, `en_US-lessac-medium`) reads `model_not_local`; it is never
fetched.

Validation runs before any loader, so a missing or partial model reads
`unavailable` with a typed reason and nothing is fetched. The TTS runner reads
only files; it has no download path at all. The bundled profile
(`agent_runtime/bundle_profiles/bundled-desktop.yaml`) also sets
`HF_HUB_OFFLINE=1`, which upstream's Piper voice download (full Hermes) honours
through a two-line fork seam in `tools/tts_tool_local.py::_resolve_piper_voice_path`.

**CPU default** (owner ruling 1: mid-range PC, no dedicated GPU): `int8` on
CPU, one English STT model and one voice. Measured below: Whisper tiny.en (ONNX
int8) meets the ≤ ~1 s budgets on the measurement machine; base.en is more
accurate and misses them. The voice the
Launcher's catalog lists is the product choice; the service loads whichever
file it is given.

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
 missing?,                       # model_partial / phonemizer_missing: the absent/empty/unparseable files
 voice_family?,                  # tts: "piper" | "kokoro" (null when neither companion file is there)
 disk_bytes?,                    # available
 device, compute_type, input_sample_rate, input_encoding,   # stt
 sample_rate}                    # tts (from the voice's .onnx.json)
```

| state | meaning |
|---|---|
| `unavailable` | `reason` ∈ `model_unset`, `model_not_local`, `model_missing`, `model_partial` (stt: `engine` names whose file list `missing` is), `model_unsupported` (stt: a NeMo folder whose `model_type` is not TDT; `+model_type`), `phonemizer_missing` (tts; `missing` names the artifact files, `voice_family` which voice wanted them), `engine_missing` (tts: onnxruntime / numpy, i.e. no speech pack), `load_failed` |
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
- Out: `pcm_s16le` mono at the voice's rate (22 050 Hz for the Piper
  medium voices, 24 000 Hz for Kokoro), pushed in chunks of at most 32 KiB raw.

Measured (2026-09-28, the machine below): a 100 ms input chunk is a **4 427-byte**
push frame; the largest synthesis chunk frame is **43 864 bytes**; a 3.5 s
sentence synthesizes as 5 chunk frames. That is well under anything the serve
transports carry already, so a side channel is not warranted.

## Streaming recognition

Neither engine is a streaming model: every pass re-decodes the take so far. The
first partial runs after 300 ms of audio, later ones after 600 ms of new audio,
one pass at a time. The final pass queues behind a partial already running;
`adopted_partial` skips it when that partial covered everything.

- **Both engines** decode in **chunks**, and a partial covers the whole take.
  Whisper's window is 30 s (onnx-asr's features cut there), so a longer take
  must be cut anyway; a Whisper pass costs about the same whatever the chunk
  length, because Whisper pads to 30 s.
- **Parakeet** Its encoder
  attends over its whole input, so one pass costs time and memory in proportion
  to the audio (measured below: 3.1 s and +0.95 GiB for 30 s, 15.8 s and
  +1.9 GiB for 120 s in one pass). The runner cuts the take every 10 s, in the
  quietest 200 ms of the 4 s before each boundary, and decodes each finished
  chunk once (cached by its bytes). A cut depends only on audio at or before its
  boundary, so the cuts of a growing take never move, and a partial or the final
  decodes only the open tail (< 10 s). Both engines decode greedily, so a
  partial and the final are the same computation.

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

**Parakeet TDT 0.6B v2 int8, measured 2026-09-28 (lane w5-hstt).** Same
machine, CPU, other sessions on the box; the bench's method and clips
(`docs/downstream/voice-model-bench-2026-09-28.md`: three LibriSpeech dev-clean
utterances, 200 ms of silence before and 300 ms after, 100 ms chunks at real
time through `handle_request`). Three runs; the three clip figures per cell.

| STT model | first words | final | WER | load | RAM (resident growth) |
|---|---|---|---|---|---|
| Parakeet TDT 0.6B v2 int8 | 0.09 / 0.08 / 0.08 s · 0.11 / 0.08 / 0.07 s · 0.11 / 0.10 / 0.11 s | 0.67 / 0.82 / 0.71 s · 0.56 / 0.67 / 0.50 s · 0.92 / 1.27 / 0.51 s | **0 / 38** (all three runs) | 5.5–5.8 s | +0.71 GiB loaded, +0.80 GiB after decoding; process peak 0.83 GiB |
| `faster-whisper-tiny.en` (same run, re-baseline) | 1.03 / 2.78 / 1.12 s | 0.80 / 0.97 / 0.70 s | 5 / 38 | 3.6 s | +0.10 GiB loaded, +0.13 GiB after |

The first call after load (1 s of audio) took 0.28–0.33 s and is not in the
figures. Every final that exceeded 0.7 s had queued behind a partial still
running. A 126-second take (the three clips eight times over, 15 cuts) held
resident growth at +0.83 GiB; the cold whole-take pass took 5.0–5.9 s and the
next pass over the same take 0.44–0.55 s (every finished chunk cached). WER
8 / 304: all eight are the same dropped "of" in "instant of panic", none at a cut.

**Whisper on onnxruntime, measured 2026-09-29 (lane w6-hwort).** Same machine
and method as the Parakeet table (the bench's three clips, three runs through
`handle_request`, CPU, other sessions on the box), run from the built speech
pack on CPython 3.14.5 (`-I -S`, the bundle's site-packages). The old engine was
re-baselined in the same sitting from the base commit's pack
(`ff012d8a9e`).

| STT model | first words | final | WER | load | RAM (resident growth) |
|---|---|---|---|---|---|
| Whisper tiny.en, ONNX int8 (onnx-asr) | 0.90 / 0.90 / 0.92 s · 0.88 / 0.88 / 0.88 s · 0.85 / 0.86 / 0.86 s | 0.58 / 0.57 / 0.61 s · 0.67 / 0.70 / 0.74 s · 0.41 / 0.44 / 0.43 s | 6 / 38 (all three runs) | 2.2 s | +172 MiB loaded, +362 MiB after decoding; process peak 442 MiB |
| `faster-whisper-tiny.en` (ctranslate2, re-baseline) | 0.89 / 0.89 / 0.90 s · 1.83 / 1.75 / 1.93 s · 0.90 / 0.87 / 0.87 s | 0.45 / 0.36 / 0.36 s · 0.53 / 0.38 / 0.58 s · 0.36 / 0.34 / 0.37 s | 5 / 38 | 2.4 s | +111 MiB loaded, +141 MiB after; peak 327 MiB |
| Whisper base.en, ONNX int8 | 1.14 / 1.13 / 1.15 s · 1.15 / 1.18 / 1.12 s · 1.81 / 1.80 / 1.90 s | 1.03 / 1.02 / 1.00 s · 1.55 / 1.42 / 1.60 s · 0.85 / 0.76 / 1.50 s | 3 / 38 | 1.4 s | +224 MiB loaded, +482 MiB after; peak 562 MiB |

The first call after load (1 s of audio) took 0.36 s (tiny) and 0.59 s (base).
One tiny.en int8 pass over a clip is 0.46–0.56 s on this CPU; the fp32 export
decoded faster here (0.33–0.44 s; this Zen 2 CPU has no VNNI) but is 151 MB,
3.7 times the download, with the same 6 / 38, so int8 ships. The errors are tiny.en's own: "fled in"
→ "flooded", "His instant of" → "This instant", "along" → "out on" (faster-whisper
made the first and third). The final is greedy where faster-whisper's used beam
5, which is most of the final-latency gap; the first-words figure no longer has
faster-whisper's 1.8 s outlier on the second clip.

**The speech pack after w6-hwort** (win32-x64, packager `--verify` and
`--verify-pack` 0 problems, `scripts/bundle_ceilings.py`'s `lzma_size`): before
(`ff012d8a9e`) 14 distributions, 158.6 MiB installed, 31.02 MiB LZMA; after,
5 distributions (onnx-asr, onnxruntime, numpy, flatbuffers, protobuf), 73.8 MiB
installed, **14.11 MiB LZMA**. Gone: ctranslate2, faster-whisper, tokenizers,
huggingface-hub, hf-xet, fsspec, filelock, pyyaml, setuptools. The pack's
`licenses.json` `review_required` went from `[ctranslate2]` (Intel OpenMP) to
`[]`; the core's stays `[]`.

**The speech pack, re-measured 2026-09-28 (lane w5-hstt, win32-x64, packager
`--verify` 0 problems, `scripts/bundle_ceilings.py`'s `lzma_size`):** before
(`312103de32`) 15 distributions, 159.51 MiB installed, 31.29 MiB LZMA; after,
16 distributions (onnx-asr added, 0.19 MiB installed with its excluded
preprocessor graphs left out; `cudnn64_9.dll` stripped, 0.25 MiB), 159.49 MiB
installed, **31.24 MiB LZMA**. Both engines decode from the built pack on the
pinned 3.14 interpreter: Parakeet transcribed clip `1272-135031-0004` exactly,
Whisper tiny.en ran on CPU int8 with no cuDNN present. Licences: the pack's
`review_required` was `ctranslate2` (embedded `intel-openmp`, `libiomp5md.dll`,
`review: true`) and `piper-tts` (piper-tts left in lane w5-htts, below); the core's is empty (the interpreter's
`vcruntime140` carries `accepted`, owner ruling item 8).

**TTS on the pack's own runner** (lane w5-htts, 2026-09-28, same machine, other
lanes running: CPU 38–65 % busy). One sentence is synthesized whole, so "first
audio" is that sentence's synthesis time. Three warm runs each; intelligibility
is faster-whisper `base.en` transcribing the WAV back.

| voice | load | first audio: S0 (one 5.5 s sentence) | first audio: S1's first sentence | Whisper heard |
|---|---|---|---|---|
| Piper `en_US-ljspeech-medium` + OpenPhonemizer | 11.2 s | 0.40 / 0.37 / 0.33 s | 0.09 s | S0 exact; S1 "…at 3.45 pm. The game is ready to play." ("and" lost); S2 every word |
| Kokoro 82M `af_heart` + misaki | 2.9 s | 1.95 / 2.10 / 1.80 s | 0.72 s | S0, S1 ("Welcome back to Eternia…") and S2 every word |

S0 "The quick brown fox jumps over the lazy dog, and then it runs back home
before dark." · S1 "Welcome back to Eternia. Your download finished at 3:45 PM
and the game is ready to play." · S2 "Hermes saved 2 files on September 28th,
2026; the update is 12.5 percent smaller." No `torch`, `piper`, `phonemizer`,
`espeakng_loader`, `misaki`, `spacy` or `num2words` module was loaded (checked
through `sys.modules`). Piper's load is mostly onnxruntime building the voice's
session (7.0 s of it on this loaded box; the phonemizer adds 0.6 s).

Before (piper-tts + espeak-ng, lessac-medium, 2026-09-28 w2): load 4.7–5.1 s,
first chunk 0.26–0.28 s for a 3.5 s sentence.

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

Speech estimates: STT = directory size × the engine's factor + its overhead —
× 3.5 + 240 MiB for Whisper (tiny.en reserves about 380 MiB against +362 MiB
measured, base.en about 500 against +482), × 1 + 256 MiB for Parakeet
(`speech_stt_engines.STT_ENGINES`) — and
TTS = voice size × 1.5 + 64 MiB (measured resident: Parakeet int8 +0.80 GiB after decoding, +0.83 GiB on a
126 s take, against 887 MiB reserved; lessac-medium +85 MiB against 154 MiB
reserved — estimates round up). Parakeet's figure holds because it decodes in
chunks: one unchunked pass over 120 s grows to +1.9 GiB.

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
