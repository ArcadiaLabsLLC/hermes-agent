# Voice model bench — 2026-09-28

Lane w3-hvoice. Measurements for the speech tier table in
`EterniaLauncher/docs/embedded_hermes/planned/BUNDLE_BUDGET_2026-09-28.md` ("Speech: the swap
points"). No product code changed. Taken on `origin/main` `08ee5074cb`.

Eternia is commercial, so every candidate carries a licence for its **code**, its **weights** and
its **training data**. A dataset licence is what disqualified Piper `en_US-lessac-medium`. This page
records licences; it is not legal advice. Rows marked **check** need an owner or legal decision.

## How it was measured

- **Machine:** AMD Ryzen 7 3700X (8 cores / 16 threads), 48 GB RAM, Windows 10, NVIDIA RTX 4090
  24 GB. Other sessions on the box kept about 4–5 of the 16 threads busy for the whole run
  (sampled per process). Absolute times are therefore a little pessimistic, but every candidate
  ran under the same load.
- **CPU by default.** Only the models that cannot keep up on CPU were also run on the GPU.
- **Speech to text:** the same method as `docs/agent-runtime-harness/runtime-speech-methods.md`
  § Latency. Audio is pushed in 100 ms chunks at real time. The partial schedule is copied from
  `agent_runtime/speech_service.py`: the first partial after 300 ms of audio, then one every 600 ms
  of new audio, on one worker, over the whole buffer. Partials use greedy decoding (beam 1) and
  the final uses beam 5. Whisper runs with the service's settings (VAD on,
  `condition_on_previous_text=False`, English). Parakeet makes its "live words" the same way, by
  re-decoding the growing buffer.
  - **First words** is the time from speech start (200 ms into the clip) to the first non-empty
    partial.
  - **Final** is the time from the last pushed chunk to the reply.
  - **Clips:** three LibriSpeech dev-clean utterances (CC BY 4.0, from
    `hf-internal-testing/librispeech_asr_dummy`: `1272-135031-0004`, `1272-141231-0003`,
    `1272-141231-0008`). Each is 4.2–5.4 s of real human speech, padded with 200 ms of silence
    before and 300 ms after.
  - **WER** is scored against the LibriSpeech transcript after lower-casing and stripping
    punctuation.
  - Each clip was run once. The first call after loading is timed separately ("first call") and
    is not counted in the clip numbers.
- **Text to speech:** three sentences (the fox sentence from the last lane plus two launcher
  lines, about 38 words and 10–12 s of audio), synthesized one sentence at a time, the way the
  service streams.
  - **First audio** is the time until the first sentence is ready.
  - **RTF** is synthesis time divided by audio length (below 1.0 means faster than real time).
  - The first call ("Hello.") is timed separately.
  - **Intelligibility:** the output was transcribed with Whisper base.en and scored against the
    text. Every candidate scored at least 2/38, because Whisper writes "riverbank" as one word;
    the table shows the errors beyond those two.
  - Cloning models were given a 10.7 s LibriSpeech reference clip (speaker 1272, CC BY 4.0).
- **Memory:** "RAM" is the growth in resident memory when the model loads. "Peak" is the
  process's peak working set, imports included.
- **Download** is the model files each engine actually fetched.
- **Runtime** is the installed size of the Python packages the engine adds on top of the current
  speech pack (onnxruntime, numpy).
- Scripts, logs, JSON results and output WAVs are in the lane's `.lane-logs/`, which is not
  committed.

## Speech to text

| Model | First words (3 clips) | Final (3 clips) | One offline decode | WER (38 words) | Load | RAM / peak | Download | Runtime it needs |
|---|---|---|---|---|---|---|---|---|
| Whisper tiny.en (faster-whisper, int8) | 1.14 / 2.52 / 1.28 s | 0.95 / 1.20 / 1.20 s | 0.53–0.66 s | 13.2 % (5) | 4.4 s | +98 / 292 MiB | 78 MB | ctranslate2 60 MB + faster-whisper 2 MB + tokenizers 8 MB + PyAV 66 MB (MIT / MIT / Apache-2.0 / BSD) |
| Whisper base.en (same) | 1.62 / 2.05 / 1.52 s | 1.60 / 1.36 / 1.70 s | 0.97–1.24 s | 7.9 % (3) | 2.0 s | +134 / 428 MiB | 148 MB | same as tiny |
| **Parakeet TDT 0.6B v2** (ONNX int8, onnx-asr) | **0.23 / 0.21 / 0.21 s** | **0.59 / 0.73 / 0.42 s** | 0.45–0.66 s | **0 %** (0) | 6.9 s | +723 / 870 MiB | 661 MB | onnx-asr 7 MB (MIT); onnxruntime is already in the pack. sherpa-onnx 1.13.8 (already a fork pin, 28 MB, Apache-2.0) can load the same model |

- **Re-baseline.** On real speech under background load, Whisper tiny.en's first words land at
  1.1–2.5 s, against the last lane's 0.98 s on a synthetic clip on an idle machine. Base.en is
  again slower than tiny. For Whisper, a final can wait behind a partial that is still running;
  Parakeet's partials are short enough that this never happened.
- **Parakeet** gets its first words in 0.21–0.23 s, about 5 to 10 times sooner than Whisper
  tiny, and made no errors where Whisper made 3–5 ("flooded disgrace", "instant panic"). Its
  cost is size: 661 MB to download and about 0.7 GB of RAM, against 78 MB and 0.1 GB for tiny.
  It also adds casing and punctuation.
- **GPU** was not measured for speech to text. Both models are already faster than real time on
  this CPU.

| STT licence | Code | Weights | Training data |
|---|---|---|---|
| Whisper tiny/base.en | faster-whisper MIT, ctranslate2 MIT | MIT ([openai/whisper](https://github.com/openai/whisper/blob/main/LICENSE)) | 680 k h of web audio, not disclosed (Whisper paper). **check**: provenance is unknown, although the weights are MIT |
| Parakeet TDT 0.6B v2 | onnx-asr MIT; ONNX export by istupakov, CC-BY-4.0 | **CC-BY-4.0** ([model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2)): commercial use allowed with attribution | Granary, about 120 k h: 10 k h human-transcribed (LibriSpeech, Fisher, VCTK, VoxPopuli, Europarl, MLS, Common Voice, AMI, NSC) plus 110 k h pseudo-labelled (YouTube-Commons, YODAS, LibriLight). NVIDIA publishes the model as commercially usable; Fisher is an LDC corpus. **check**: attribution text for the About box |

## Text to speech

All CPU unless marked. For a single-voice model, "Voices" means one fixed voice.

| Candidate | Load | First audio (1st sentence) | RTF | RAM / peak | Download | Runtime it needs | Errors beyond "riverbank" | Voices |
|---|---|---|---|---|---|---|---|---|
| Piper `en_US-ljspeech-medium` | 4.9 s | 0.25 s | **0.058** | +111 / 253 MiB | 64 MB | piper-tts 45 MB (**GPL-3.0**) | 0 | one fixed voice |
| Piper `en_US-kristin-medium` | 5.3 s | 0.21 s | 0.058 | +111 / 251 MiB | 64 MB | same | 0 | one fixed voice |
| Piper `en_US-norman-medium` (male) | 5.7 s | 0.22 s | 0.058 | +111 / 251 MiB | 64 MB | same | 0 | one fixed voice |
| Piper `en_GB-cori-high` | 5.8 s | 0.79 s | 0.239 | +161 / 305 MiB | 114 MB | same | 3 ("duck", "while come", "Itania") | one fixed voice |
| Piper `en_US-libritts-high` (speaker 0) | 3.1 s | 0.93 s | 0.232 | +182 / 324 MiB | 137 MB | same | 0 | **904 built-in speakers** in one file |
| Kokoro 82M fp32 (kokoro-onnx, `af_heart`) | 3.7 s | 1.97 s | 0.579 | +367 / 508 MiB | 354 MB (326 model + 28 voices) | kokoro-onnx 1 MB + espeakng-loader 19 MB + phonemizer 1 MB (**GPL-3.0**) | 0 | 54 preset voices, blendable; no cloning |
| Kokoro 82M int8 | 3.2 s | 7.00 s | 1.709 | +153 / 303 MiB | 121 MB | same | 0 | same. The int8 build is about 3 times *slower* on this CPU, so do not ship it |
| Pocket TTS 100M, PyTorch (`pocket-tts` 3.1, voice `alba`) | 5.8 s warm (54 s with first download) | 1.65 s | 0.457 | +987 / 1113 MiB | 225 MB | torch CPU 499 MB (venv 775 MB) | 0 | presets; cloning from a WAV (the cloning weights are gated behind a prohibited-use agreement) |
| Pocket TTS int8 ONNX (sherpa-onnx, cloning from the reference clip) | 1.5 s | 1.98 s | 0.578 | +306 / 606 MiB | 203 MB | sherpa-onnx 28 MB (already a fork pin) | 0 | clones |
| Chatterbox Nano 110M (`chatterbox-tts` from git `5de7a54`), CPU | 217 s (with download) | 38.7 s | **10.5** | +2974 / 4456 MiB | 3.0 GB fetched (1.94 GB used) | torch cu124 4.7 GB (venv 5.4 GB) | 2 | zero-shot cloning, `[laugh]`-style tags, PerTh watermark on output |
| Chatterbox Nano, **GPU** | 49 s | 1.68 s | 0.406 | +1869 MiB, VRAM 2.2 GB | same | same | 1 | same |
| Qwen3-TTS 0.6B Base, PyTorch (`qwen-tts` 0.1.1), **GPU** bf16 | 344 s (with download) | 15.4 s | **3.43** | +2051 MiB, VRAM 2.4 GB | 2.5 GB | torch cu128 4.4 GB (venv 5.1 GB); flash-attn is not installable here, so the slow attention path ran | 0 | clones from 3 s; the CustomVoice variant has 9 speakers; VoiceDesign is 1.7B only |
| Qwen3-TTS 0.6B Base, community ONNX `cpu_int4` (onnx-community, runs without PyTorch, KV-cache path) | 11.5 s | 28.6 s | **7.69** | +1701 / 2351 MiB | 1.6 GB | transformers 55 MB + librosa/numba/llvmlite about 135 MB | 0 | clones |

- **Piper medium voices** are the only candidates at about 0.2 s to first audio and RTF 0.06.
  The high-quality Piper builds are 4 times slower but still well under real time.
- **Kokoro fp32** is fast enough overall (RTF 0.58). Its first sentence takes about 2 s, so it
  needs sentence pipelining.
- **Pocket TTS** is the only voice-cloning model that runs faster than real time on this CPU.
  The ONNX build runs without PyTorch, on a package the fork already pins.
- **Chatterbox Nano** needs the GPU. On CPU here it ran at RTF 10.5, far from the vendor's
  claim of 3x real time on 8 cores. Background load was present, and PyTorch was left on its
  default thread count; this was not investigated further. Even on a 4090 it only reaches
  RTF 0.41.
- **Qwen3-TTS 0.6B** did not reach real time either way: RTF 3.4 on the 4090 without
  flash-attn, 7.7 on CPU as int4 ONNX. It is out for interactive use until a faster runtime
  exists.

| TTS licence | Code | Weights | Training data | Commercial? |
|---|---|---|---|---|
| Piper (all voices) | **piper-tts 1.8.0 is GPL-3.0-or-later** (OHF-Voice `piper1-gpl`; the wheel's METADATA says so), and it links espeak-ng (GPL-3.0) | per voice, below | per voice, below | **check**: the speech pack we already ship contains this GPL wheel, whichever voice is picked |
| `ljspeech-medium` | — | trained from scratch ([card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/medium/MODEL_CARD)) | [LJ Speech](https://keithito.com/LJ-Speech-Dataset/), public domain | data OK |
| `kristin-medium` / `norman-medium` / `cori-high` | — | trained from scratch by Bryce Beattie ([cards](https://brycebeattie.com/files/tts/)) | LibriVox recordings, public domain (in the US) | data OK; LibriVox is public domain in the US and may not be elsewhere, **check** |
| `libritts-high` | — | trained from scratch on train-clean-360 ([card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/libritts/high/MODEL_CARD)) | [LibriTTS](http://www.openslr.org/60/), CC BY 4.0 | data OK, attribution needed |
| Piper voices to *avoid* | — | `joe`, `mike` (CC0 data), `alba`, `vctk`, `aru` (CC BY 4.0 data) and `libritts_r` are all **fine-tuned from lessac**, so they inherit the checkpoint that lessac's licence disqualified. `amy`/`danny`/`kathleen`-low are fine-tuned from `ryan` (CC BY-NC-SA). `hfc_*`, `ryan`, `semaine` and `l2arctic` use non-commercial data | — | no |
| Kokoro 82M | kokoro-onnx MIT; phonemizer and espeak-ng **GPL-3.0** | Apache-2.0 ([hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)) | Public-domain audio, Apache/MIT-licensed audio, CC BY 3.0/4.0 sets (Koniwa, SIWIS), and **synthetic audio from closed commercial TTS providers** | **check**: GPL phonemizer, and whether the providers' terms allow training on that synthetic audio |
| Pocket TTS | MIT ([kyutai-labs/pocket-tts](https://github.com/kyutai-labs/pocket-tts)); sherpa-onnx Apache-2.0 | CC-BY-4.0, with a prohibited-use clause (no cloning without consent). The ONNX export's LICENSE file is CC-BY-4.0, but the sherpa README calls it "non-commercial": the two contradict | 88 k h of public sets ([paper](https://arxiv.org/abs/2509.06926) App. D): LibriHeavy, GigaSpeech, VoxPopuli, TED-LIUM 3, Earnings-22, SPGISpeech, AMI, **Emilia** (the original [Emilia is CC BY-NC 4.0](https://huggingface.co/datasets/amphion/Emilia-Dataset); only its YODAS split is CC BY 4.0) | **check**: which Emilia split was used, and the README/LICENSE contradiction |
| Chatterbox Nano | MIT ([resemble-ai/chatterbox](https://github.com/resemble-ai/chatterbox)) | MIT ([card](https://huggingface.co/ResembleAI/chatterbox-nano)) | not disclosed | **check**: data provenance unknown; every output carries Resemble's PerTh watermark |
| Qwen3-TTS 0.6B | Apache-2.0 ([QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)) | Apache-2.0 | "over 5 million hours", sources not named ([report](https://arxiv.org/abs/2601.15621)) | **check**: data provenance unknown |

## Proposed tiers — proposal, owner decides

| Tier | Speech to text | Voice | Why | Disk (models) | RAM |
|---|---|---|---|---|---|
| **Fast** (low-end PCs, smallest download) | Whisper tiny.en | Piper `en_US-ljspeech-medium` or `kristin-medium` (female) / `norman-medium` (male) | Voice at about 0.2 s, RTF 0.06; STT is small but its first words take 1–2.5 s and it gets about 13 % of words wrong | 78 + 64 MB | about 0.2 GB |
| **Balanced** (default on most PCs) | **Parakeet TDT 0.6B int8** | Piper medium, as in Fast | Words in about 0.2 s, no errors on the test clips; the voice stays instant | 661 + 64 MB | about 0.85 GB |
| **Best** (8 GB+ RAM) | Parakeet | Kokoro 82M fp32 | Most natural of the CPU voices at RTF 0.58, but about 2 s to the first sentence | 661 + 354 MB | about 1.1 GB |
| **Characters** | same as the player's tier | Stock NPC voices: Piper `libritts-high` (904 speakers in one 137 MB file, RTF 0.23). Cloned or designed voices: Pocket TTS ONNX on CPU (RTF 0.58), or Chatterbox Nano on GPU (RTF 0.41, 2.2 GB of VRAM) | Only Piper `libritts-high` is licence-clean. Both cloning options have open **check** rows | 137 MB / 203 MB / 3 GB | +0.2 / +0.3 / +1.9 GB |

- **Dropping Whisper** once Parakeet is the default also drops ctranslate2 (60 MB) and
  tokenizers from the speech pack. Parakeet then runs on onnxruntime, the engine the voices
  already use: that is the budget page's option 3. Keeping tiny.en for the Fast tier keeps
  ctranslate2.
- **The GPL question blocks every Piper and Kokoro tier as bundled today.** Both reach
  espeak-ng through a GPL-3.0 Python layer. Piper is also GPL itself since `piper1-gpl`.
  Measured here, not resolved.
- **Not recommended:** Qwen3-TTS 0.6B (not real time on either device), the Kokoro int8 build
  (slower than fp32), and Chatterbox Nano on CPU.

## Skipped

- **Chatterbox Nano ONNX** (`KitsuMate/chatterbox-nano-v2-onnx`): the repo ships graphs but no
  Python runner. The official PyTorch path was measured instead.
- **Qwen3-TTS through PyTorch on CPU:** not run. The int4 ONNX build (RTF 7.7) already shows
  that CPU is out of reach.
- **Speech to text on GPU:** not needed, since both engines run faster than real time on CPU.
- **Streaming inside a sentence** (Pocket's `generate_audio_stream`, Qwen's streaming mode):
  not measured. First audio here is the time to the first *sentence*, which overstates what a
  streaming engine would deliver.
