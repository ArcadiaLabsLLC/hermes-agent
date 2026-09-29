# Bundled desktop — import closure and package list (2026-09-28)

What the **bundled-desktop** profile (`agent_runtime/bundle_profiles/bundled-desktop.yaml`) ships, per the standing rule *bundle only what is needed* (launcher `EterniaLauncher/docs/embedded_hermes/planned/PROFILE_MATRIX_2026-09-28.md`). Regenerate (the tables below are the `--markdown` output, pasted unedited):

```
python scripts/bundle_profile_closure.py --profile bundled-desktop --json <out.json> --markdown <out.md>
```

The script exits 1 (`REFUSED: …`) when an omitted distribution is imported unguarded, when an omitted distribution is a requirement of a shipped one, when `packaging.extras` names no pyproject extra, when `packaging.dynamic_distributions` names no base dependency, or when a `packaging.placeholder_distributions` entry is imported by kept first-party code or is a base dependency.

## Method, and which numbers are estimates

- **Static walk** (`ast`): every `import`, module-level AND inside functions, plus `importlib.import_module("literal")` calls (this is how `agent.relay_runtime` loads `nemo_relay`, which the first walk missed), from the manifest's `packaging.roots`; the walk never follows an import into `packaging.switched_off_modules`. Lazy imports count, so "reached" is an **upper bound**.
- **What ships** is decided by the distribution's declaration in `pyproject.toml`, markers evaluated for the bundle target (win_amd64, CPython 3.14): a **base** dependency ships unless `packaging.omitted_distributions` drops it (refused unless every import site in the kept modules is guarded by `try`/`suppress` catching `ImportError`); an **optional extra** ships only when `packaging.extras` names one of its extras — full Hermes installs extras lazily and their import sites tolerate absence, and the profile turns lazy installs off, so an unshipped extra is an unavailable feature, never a download; an undeclared distribution the walk reaches ships and is listed; every shipped distribution's requirements ship with it.
- **Pinned** = a switched-off module a kept module imports at module level, unguarded: it loads whatever the config says, so its module-level imports count. A guarded module-level import is already a seam.
- **Instrumented boot probe**: importing the roots in a fresh interpreter and reading `sys.modules`. "Boot" = loaded at import time (a **lower bound**).
- **Excludable** = reached only through a switched-off module.
- **Measured** sizes: on-disk bytes of each installed distribution's RECORD files in the live Hermes venv (CPython 3.12.14, win_amd64). **Estimated**: distributions the live venv does not have (the speech stack) are sized by their uv.lock wheel. **Wheels (compressed)**: every shipped distribution's uv.lock wheel (cp314, else cp312/abi3 win_amd64, else `none-any`) — the number comparable to the installer ceiling.

## Owner rulings (2026-09-28)

1. **`nemo-relay` is dropped from bundled desktop.** Bundled runs `NoopRelayRuntime`: no managed execution, no Relay plugins, no shared metrics. Mechanism: `packaging.omitted_distributions` (the one import site, `agent.relay_runtime._load_nemo_relay`, now raises a typed `RelayUnavailable` that `RelayHostRegistry.for_profile` turns into the Noop host); the profile also pins `telemetry.shared_metrics.enabled: false`. Full Hermes unchanged.
2. **No Qwen OAuth in bundled.** The profile sets upstream's existing per-provider switch `providers.qwen-oauth.enabled: false`. The runtime resolver refuses it (named, and now also when "auto" lands on it), the machine sign-in refuses with reason `provider_disabled`, and the login catalog and credential-visibility snapshot leave it out (the Qwen CLI's token file is never read). Qwen models stay reachable through OpenRouter or an API-key provider.
3. **Bedrock, Vertex, Azure identity and Mistral stay out of bundled** (their extras are not shipped).
4. **HEIC decoding stays out** (`pillow-heif` omitted); the Launcher handles image formats.

## Before → after (lane w2-hslim)

| | before | after |
|---|---:|---:|
| distributions shipped | 121 (89 measured + 32 estimated) | 91 (71 + 20) |
| installed, measured | 222.3 MiB | 130.2 MiB |
| not installed, wheel estimate | ~124.6 MiB | ~113.6 MiB |
| **all shipped, as compressed wheels** | ~192.8 MiB | **~149.5 MiB** |
| — core only (no speech extras / speech roots) | — | **~36.3 MiB** |
| boot set (third-party loaded at import) | 26 dists, 39.6 MiB | 25 dists, 39.2 MiB |
| first-party modules kept by the walk | 2161 | 2135 |
| pinned switched-off modules | 12 | 9 |

What moved it:

- **Extras are not base.** `discord-py`, `python-telegram-bot`, `boto3`/`botocore` (Bedrock), `google-auth` (Vertex), `azure-identity`, `mistralai`, `elevenlabs`, `ddgs`, `qrcode`, `pip`, `soundfile`, `pilk`, `agent-client-protocol`, `aiohttp` are optional extras the walk reaches; the profile ships only `anthropic`, `mcp`, `fal`, `piper`, `stt-whisper`. Bedrock, Vertex, Azure identity and Mistral are therefore **unavailable** in bundled Hermes (their providers raise their own "install the extra" error; lazy installs are off). The messaging SDKs reached via `cron.scheduler → cron.scheduler_delivery → tools.send_message_tool → tools.send_message_senders` and `gateway.run → gateway.channel_directory` are extras, so they no longer count.
- **`nemo-relay` omitted** (24.3 MiB installed, 9.2 MiB wheel) — ruling 1.
- **`pillow-heif` omitted** (27.6 MiB installed): both import sites (`agent.image_routing`, `tools.vision_tools_image_prep`) are guarded; HEIC/HEIF photos cannot be decoded, AVIF still decodes (native in Pillow 12).
- **Switched off, not packaged** (matrix "—"): voice mode glue `hermes_cli.voice`; checkout-bound `gateway.code_skew`, `hermes_cli.update_cmd*` / `update_completion` / `update_inventory` / `worktree_cmd` / `relay_plugin_migrate`; dev tooling `agent_runtime.doctor_extensions`. `cron.scheduler → gateway.code_skew → hermes_cli.main` is cut at `code_skew` (both cron call sites are `try/except Exception → None`, the right answer for a wheel).
- **Seam:** `hermes_cli.web_server_config` imports `tools.wake_word._PROVIDER_PREFERENCE` guarded, so the dashboard schema loads without wake word (offers only "auto").
- **Tree corrections:** `hermes_cli.web_routers.local_models` is no longer listed as switched off — the profile's route gate refuses its download routes and requires them mounted, so it ships. `hermes_cli.worktree_ops` (kanban's worktree workspaces import it) and `agent_runtime.harness_doctor` (the harness parser registers `harness doctor` at import) stay packaged.

## What stayed, and why

- **Speech (~113 MiB compressed)**: `piper-tts` 32.5 (all-language espeak data), `av` 26.3 (PyAV, via faster-whisper), `ctranslate2` 18.6, `onnxruntime` 13.7, `numpy` 11.9, `hf-xet` 3.9, `tokenizers` 2.7. Owner ruling D4 expects ~25–35 MB once PyAV and non-English Piper data are dropped — that is the speech lane's work, not an import seam.
- **`pywin32`** (9.2 MiB wheel): `portalocker` requires it on Windows (`concurrent-log-handler` → Hermes logging; MCP loop), and `tui_gateway.host_supervisor` imports `win32con`/`win32file`/`ntsecuritycon`. Only a few of its modules are used; stripping the rest is a packaging-step (wheel build) job.
- **Shell family and messaging adapters are pinned**: `tools.terminal_tool` (by `tools.delegate_tool`), `tools.terminal_tool_lifecycle` (by `run_agent`, `agent.tool_executor`, `agent.chat_completion_helpers`), `tools.environments.local` (`hermes_subprocess_env`, used by `tui_gateway.server`, `host_supervisor`, `codex_app_server`, `process_registry`), `gateway.platforms.*` (by the `gateway.run` family and `gateway.relay`). The matrix says these features are **present, off** on bundled desktop, so their code ships; moving the helpers out of those upstream modules is a non-additive upstream refactor. Tool discovery still imports the shell-family tool modules at boot (disabled toolsets are subtracted after registration).
- **Unguarded imports into switched-off modules: 442** (`unguarded_switched_off_imports` in the JSON) — lazy imports that would raise if the bundle omitted the module and the line ran. Most target the pinned shell/messaging modules above (they ship); the rest are behind the new switches or in off features.

## Switches built (default = today's behaviour; the profile turns each off)

| config key | chokepoint | off means |
|---|---|---|
| `mcp.stdio_servers` | `tools.mcp_tool_common.mcp_server_enabled` (the one reader of `enabled`) | stdio servers read as disabled on every surface; HTTP servers unaffected |
| `tts.piper.download_voices` | `tools.tts_tool_local._resolve_piper_voice_path` | a voice name not on disk is an error, never a `piper.download_voices` run |
| `terminal.external_backends` | `tools.terminal_tool_backends._create_environment` | every backend but `local` is refused before its builder runs |
| `gateway.platform_adapters` | `gateway.run_adapters.GatewayAdapterLifecycleMixin._create_adapter` | the messaging gateway starts no adapter, configured or not |
| `updates.checkout_bound` | `agent_runtime.build_stamp._resolve`, `agent_runtime.dirty_state.repo_dirty_states` | no git: the stamp comes from `.hermes_build_sha` beside the package (the wheel build must bake it), repos report `checkout_bound_off` |
| `voice.mode_enabled` | `tui_gateway.methods_voice` (`voice.toggle on`, `wake.start`), `hermes_cli.cli_voice_mixin._enable_voice_mode` | voice mode and wake word are refused |

All read through one helper, `hermes_cli.config.config_switch`. The profile also sets the existing `auth.adopt_external_logins: false` (Claude Code / Codex CLI logins never borrowed) and, for Qwen (whose only token store is the Qwen CLI's own file), the existing `providers.qwen-oauth.enabled: false` — ruling 2. Still unswitched: `agent_runtime.repo_context` (affected-repo resolution and harness worktree inventory consult git).

## Measured bundle (lane w2-hwheel, 2026-09-28)

Built for real on Windows x64 with `scripts/bundle_profile_package.py` (the packaging step) against this tree, then started. Scratch outputs only; nothing downloaded into the tree.

The generated tables further down predate this lane's changes to the closure (bundled plugin roots, the target-excluded / guard-only classification, the speech pack split); the per-package table at the end of this section is the measured one.

```
python scripts/bundle_profile_package.py --profile bundled-desktop --target win32-x64 --out <dir> [--bake-with <target python>]
python scripts/bundle_profile_package.py --verify <core dir> [--verify-pack <pack dir>]
```

**How it builds.** (1) *Pool*: `uv export --frozen` of the base dependencies plus `packaging.extras` and every engine pack's extras, markers evaluated by the packager for the target (uv 0.11.14's cross-target environment reports no `platform_machine == 'AMD64'` for `x86_64-pc-windows-msvc`), installed `--no-deps --require-hashes --only-binary :all:` into a staging `--target`: uv.lock's pins and hashes, nothing resolved. (2) *Plan*: this script's closure decides every distribution (it runs in a child `-I -S -B` interpreter whose only site directory is the pool, target environment set); first-party modules are the closure walk's kept modules plus its bundled plugin directories (`packaging.plugins`, hyphenated ones indexed as `plugins.<dir_>`) plus every switched-off module kept code imports unguarded (pinned or lazy), with its module-level imports and parent packages. (3) *Copy*: tracked files only (`git ls-files`); distribution RECORD files minus `__pycache__`, test directories and `packaging.excluded_data`; `app/.hermes_build_sha` (the stamp `agent_runtime.build_stamp` reads when `updates.checkout_bound` is off — measured: the ready frame's `build.source` is `build_sha_file`). (4) *Verify* (plan D4): the plan is recomputed from the source tree and the bundle's OWN site-packages; any extra or missing first-party module or distribution, closure refusal, file no distribution owns, test file, stray bytecode or excluded data fails the build (exit 1). It caught one real miss while this lane ran (three `plugins.platforms.telegram` modules loaded through a package `__init__`).

**No wheel.** `setup.py` refuses `bdist_wheel` outside Nix (upstream's guard), and upstream's own assembler (`scripts/build/agent.py`) ships source layouts with a PEP 621 dist-info rather than a wheel. The packaging step does the same (`write_metadata`), so the "wheel" is the reproducible `app/` tree at a commit.

**Two outputs (owner, 2026-09-28): speech engines download on first use.** `packaging.packs.speech` holds the `speech-tts`, `stt-whisper` and `stt-parakeet` extras (`piper` instead of `speech-tts` until lane w5-htts); the core bundle ships the profile's closure without them, the speech pack ships only what the closure adds with them. Bundled Hermes finds an installed pack through `HERMES_ENGINE_PACKS` (os.pathsep list of pack `site-packages` directories), read by `hermes-engine-packs.pth`, which the packager writes into the core `site-packages`: `site` runs its one `import` line at every interpreter start (conversation workers included) and adds only directories that exist. No pack: `faster_whisper` / `onnxruntime` are not importable and both providers report unavailable (measured, `find_spec` / `_importable` → False); pack present: STT transcribes from the pack (measured below).

### Interpreter

CPython **3.14.7**, the python-build-standalone `install_only` build PM already pins (`pm/lock.json`), for every desktop target, recorded in `agent_runtime/bundle_profiles/interpreters.lock.json` (URL + SHA-256 per target, the Windows prune list, the layout; a test fails if it drifts from PM's pin). Not 3.12: `uv.lock` resolves only for Python ≥ 3.14 and every base dependency carries `python_version >= '3.14'`, so a 3.12 bundle would install no core dependencies (the 3.12 figures above are the live venv's). Not python.org's embeddable zip on Windows, although it is smaller (12.7 MB zip vs 49.5 MB): its SQLite is **3.50.4**, which Hermes flags as vulnerable to the WAL-reset corruption bug and downgrades to journal_mode=DELETE on every store (measured: five warnings per start); the PBS build links SQLite **3.53.1** and OpenSSL 3.5.8. Windows prune (in the lock): PDBs, pip, ensurepip, idlelib, tkinter/tcl, turtledemo, `_test*` modules, include, libs, Scripts — 147.3 → **35.8 MiB** installed. Start: `python -I -m hermes_cli.main harness serve --ndjson` (`-I` keeps PYTHON* and the user site out).

### Sizes (Windows x64, installed interpreter + bundle)

| output | installed MiB | zip -9 MiB | LZMA2 -9 (xz) MiB |
|---|---:|---:|---:|
| core: interpreter + app + site-packages, source only | **173.11** | 61.53 | **38.71** |
| core, bytecode baked (`unchecked-hash`, stdlib included) | 274.05 | 106.27 | 61.46 |
| speech pack, source only | ~~225.59~~ ~~159.51~~ **158.64** | ~~78.23~~ 52.02 | ~~49.32~~ ~~31.30~~ **31.01** |
| speech pack, bytecode baked (pre-w3-hfix, with PyAV) | 244.21 | 85.78 | 53.43 |
| core app + site-packages only, source only (w3-hfix: + tzdata, socksio) | 141.22 | 51.02 | 31.61 |

**Re-measured by lane w3-hfix (2026-09-28)** against this tree: the speech pack without PyAV
(15 distributions, 1,657 files) is 159.51 MiB installed, 52.02 MiB zip -9, **31.30 MiB LZMA2 -9**
— PyAV's 66.07 MiB is exactly the drop. The core now also carries `tzdata` (0.56 MiB) and
`socksio` (0.04 MiB); its app + site-packages measure 141.22 / 51.02 / 31.61 MiB (the rows above
that include the interpreter were not re-taken; add the pruned interpreter's 35.8 MiB installed).
`--verify` on the core and `--verify-pack` both read 0 problems, and the core's verify now also
resolves `America/New_York` with `zoneinfo` from the bundle's site-packages alone
(`named_timezone_problems`: `-I -S`, TZPATH cleared). Live under CPython 3.14.5 with core + pack
on the path and no PyAV: `find_spec("av")` is None, the placeholder registers,
`import faster_whisper` succeeds, and a file decode answers `file_decode_unavailable`.

7-Zip is not installed on the build machine; the LZMA2 column is Python's `lzma` (preset 9, the codec 7z and Inno Setup use). Against the D4 ceiling (installer delta ≤ ~80 MB, excluding models): the core is ~39–61 MiB compressed depending on bytecode; the speech pack is a first-use download.

### Time to ready (serve's `{"event":"ready"}` frame, empty `HERMES_HOME`)

| install | 1st start | 2nd | 3rd |
|---|---:|---:|---:|
| core, source only (1st start compiles bytecode) | 9.10 s | 1.96 s | 1.85 s |
| core, baked | **2.54 s** | 1.69 s | 1.58 s |
| core, baked, speech pack on the path | 2.20 s | 1.71 s | — |

### PyAV

faster-whisper 1.2.1 takes a float32 numpy array (`transcribe()` calls `decode_audio` only for a non-array), but `faster_whisper/audio.py` imports `av` at module top, so `import faster_whisper` fails without PyAV. Proved: with `av` blocked, the import raises `ModuleNotFoundError: av`; with an `av` placeholder in `sys.modules` it imports and transcribes a 13 s clip passed as a 16 kHz float32 array (tiny.en, 1.7 s).

**Dropped (lane w3-hfix).** `packaging.placeholder_distributions: {av: …}` — the closure never follows `av` under faster-whisper (refused if kept first-party code imports it or it is a base dependency). `agent_runtime/speech_decode.py` registers the placeholder in `SpeechEngines.load_stt` before upstream's loader imports faster_whisper (a no-op when PyAV is installed). No second decode path is bundled, so a voice-note FILE through upstream's `_transcribe_local` answers `{success: false, state: "unavailable", reason: "file_decode_unavailable"}` before any model loads (fork seam, `tools/transcription_tools.py`); the Launcher sends raw PCM, which never needs it.

### Text-to-speech without GPL code (lane w5-htts)

Owner ruling 2026-09-28 (second sitting, item 2): the speech pack ships no GPL
code. `piper-tts` (GPL-3.0, espeak-ng compiled into `espeakbridge`, plus its
`espeak-ng-data`) is gone from the pack; so is the lane-w3-hfix arrangement
that shipped English espeak data beside each voice (the seven-file set and its
`espeak_data_partial` / `espeak_data_missing` checks, and the
`piper.espeak_data_dir` seam in `tools/tts_tool_local.py`, which is back to
upstream's text). In their place:

- **Runner** — `agent_runtime/speech_onnx_voice.py`, on `onnxruntime` (MIT) +
  `numpy` (BSD), the `speech-tts` extra: Piper VITS voices (ids from the voice's
  `phoneme_id_map`) and Kokoro 82M (ids from Kokoro's vocabulary, style row
  from `voices-v1.0.bin`).
- **Phonemizers** — `agent_runtime/speech_phonemize.py` runs two downloadable
  artifacts (`.onnx` + `.json`), placed by the Launcher beside the voice they
  serve; code in the pack, weights and dictionaries in the artifact:

  | artifact | size | SHA-256 (as exported here) | licence |
  |---|---:|---|---|
  | `openphonemizer-en_us.onnx` | 61 437 915 | `b0557ca5639d839d77d040c2610f2b1e95f584379cc1cdfa5c4984fb3d8f1b78` | BSD-3-Clause-Clear (OpenPhonemizer checkpoint) |
  | `openphonemizer-en_us.json` | 9 223 033 | `36dda6260c7e560a4d846528387fd07ababcd1012a52b530063fefadd5987db0` | BSD-3-Clause-Clear (its dictionary) |
  | `misaki-en_us-g2p.onnx` | 3 438 244 | `757759c3e3ccb0bf59c379b1671c9834a27543ceaefd6846850823633b9665a1` | Apache-2.0 (`PeterReid/graphemes_to_phonemes_en_us`) |
  | `misaki-en_us-g2p.json` | 5 724 857 | `8a8e3350713b0a00102425a5d5bd6b58b34854c74a3e8d837589f55212c51658` | Apache-2.0 (misaki lexicons; Kokoro vocabulary) |

  Made by `scripts/phonemizer_openphonemizer_onnx.py` (torch 2.14 CPU,
  deep-phonemizer 0.0.19, `openphonemizer/ckpt` `best_model.pt` 175 008 823 B;
  `--check 1000`: 1 000 / 1 000 dictionary words give the identical frame
  argmax in torch and ONNX) and `scripts/phonemizer_misaki_g2p_onnx.py`
  (misaki `fba1236595f2`, transformers 5.17; `--check 500`: 500 / 500 words
  decode identically to `generate`). The ONNX bytes are not reproducible run to
  run (the exporter's graph names), so the SHA-256 that counts is the one of the
  file uploaded for the catalog. An int8 OpenPhonemizer (23 487 495 B) agreed on
  959 / 1 000 words; fp32 is what the catalog should carry.
- **Dialect.** OpenPhonemizer writes espeak's `en-us`; the three catalog
  voices (`ljspeech`, `kristin`, `norman`) were trained on espeak's British
  `en`, where `ɑː` is the vowel of "dark". Unmapped, Whisper heard "fox" as
  "farks" and "dog" as "dart"; `rp_from_us` maps the difference and the same
  sentence transcribes exactly.
- **Measured** (the contract doc, "Latency — measured"): Piper ljspeech first
  audio 0.33–0.40 s for a 5.5 s sentence, Kokoro 1.8–2.1 s; Whisper `base.en`
  heard every word of three test sentences from Kokoro and all but one "and"
  from Piper.
- **Licences.** The speech pack's `licenses.json` (win32-x64, rebased on
  `aae4d60d02`, with w5-hstt's Parakeet): 14 components, no GPL / LGPL anywhere;
  `review_required` is only `ctranslate2` (embedded `intel-openmp`, w5-hstt's
  row, not GPL). No `piper`, `phonemizer`, `espeakng_loader` or
  `espeak-ng-data` file in either output. `--verify <core> --verify-pack <pack>`:
  0 problems. Pack 158.64 MiB installed, 31.01 MiB LZMA.

### Every package, and which output it lands in

Installed MiB, source only (no bytecode), Windows x64.

| package | version | MiB | output |
|---|---|---:|---|
| av | 18.1.0 | 66.07 | **dropped** (w3-hfix: placeholder, arrays only) |
| ctranslate2 | 4.8.1 | 59.68 | speech pack |
| hermes-agent (first-party app/, skills, locales, plugins) | — | 45.35 | core |
| onnxruntime | 1.29.0 | 39.27 | speech pack |
| numpy | 2.4.3 | 32.68 | speech pack |
| pywin32 | 311 | 19.05 | core |
| pillow | 12.3.0 | 14.07 | core |
| cryptography | 50.0.1 | 10.02 | core |
| hf-xet | 1.6.0 | 9.35 | speech pack |
| firecrawl-anydoc | 0.2.4 | 8.29 | core |
| tokenizers | 0.23.1 | 7.57 | speech pack |
| pywinpty | 3.0.5 | 6.61 | core |
| pydantic-core | 2.46.4 | 5.35 | core |
| pygments | 2.21.0 | 4.45 | core |
| openai | 2.24.0 | 3.88 | core |
| huggingface-hub | 1.24.0 | 3.01 | speech pack |
| setuptools | 83.0.0 | 2.64 | speech pack |
| pydantic | 2.13.4 | 1.81 | core |
| wcwidth | 0.8.2 | 1.72 | core |
| protobuf | 6.33.6 | 1.57 | speech pack |
| anthropic | 0.87.0 | 1.47 | core |
| prompt-toolkit | 3.0.52 | 1.33 | core |
| faster-whisper | 1.2.1 | 1.32 | speech pack |
| rich | 14.3.3 | 1.19 | core |
| mcp | 2.0.0 | 1.14 | core |
| pytz | 2026.3.post1 | 0.96 | core |
| tzdata | 2025.3 | 0.56 | core (w3-hfix: `packaging.dynamic_distributions`, stdlib `zoneinfo`) |
| snowballstemmer | 3.1.1 | 0.74 | core |
| fastapi | 0.133.1 | 0.74 | core |
| fsspec | 2026.7.0 | 0.64 | speech pack |
| websockets | 15.0.1 | 0.64 | core |
| cffi | 2.1.1 | 0.59 | core |
| charset-normalizer | 3.5.1 | 0.58 | core |
| rpds-py | 2026.6.3 | 0.56 | core |
| ruamel-yaml | 0.18.16 | 0.54 | core |
| anyio | 4.14.2 | 0.49 | core |
| jiter | 0.16.0 | 0.48 | core |
| pyyaml | 6.0.3 | 0.46 | speech pack |
| psutil | 7.2.2 | 0.43 | core |
| python-dateutil | 2.9.0.post0 | 0.42 | core |
| httpx2 | 2.7.0 | 0.42 | core |
| urllib3 | 2.7.0 | 0.41 | core |
| click | 8.4.2 | 0.41 | core |
| idna | 3.19 | 0.37 | core |
| fire | 0.7.1 | 0.36 | core |
| mcp-types | 2.0.0 | 0.35 | core |
| filelock | 3.32.4 | 0.34 | speech pack |
| httpx | 0.28.1 | 0.33 | core |
| jsonschema | 4.26.0 | 0.32 | core |
| httpcore2 | 2.7.0 | 0.28 | core |
| markdown-it-py | 4.2.0 | 0.28 | core |
| httpcore | 1.0.9 | 0.27 | core |
| tqdm | 4.70.0 | 0.27 | core |
| packaging | 26.0 | 0.26 | core |
| uvicorn | 0.41.0 | 0.26 | core |
| starlette | 1.3.1 | 0.25 | core |
| certifi | 2026.5.20 | 0.23 | core |
| attrs | 26.1.0 | 0.22 | core |
| opentelemetry-api | 1.39.1 | 0.20 | core |
| requests | 2.33.0 | 0.20 | core |
| pycparser | 3.0 | 0.19 | core |
| typing-extensions | 4.16.0 | 0.17 | core |
| msgpack | 1.2.1 | 0.17 | core |
| distro | 1.9.0 | 0.11 | core |
| pyjwt | 2.13.0 | 0.11 | core |
| python-dotenv | 1.2.2 | 0.10 | core |
| python-multipart | 0.0.32 | 0.10 | core |
| h11 | 0.16.0 | 0.10 | core |
| concurrent-log-handler | 0.9.29 | 0.10 | core |
| fal-client | 0.13.1 | 0.09 | core |
| flatbuffers | 25.12.19 | 0.08 | speech pack |
| croniter | 6.0.0 | 0.08 | core |
| pathvalidate | 3.3.1 | 0.08 | speech pack |
| importlib-metadata | 8.7.1 | 0.07 | core |
| docstring-parser | 0.18.0 | 0.07 | core |
| portalocker | 3.2.0 | 0.06 | core |
| truststore | 0.10.4 | 0.06 | core |
| referencing | 0.37.0 | 0.06 | core |
| typing-inspection | 0.4.4 | 0.05 | core |
| colorama | 0.4.6 | 0.05 | core |
| jsonschema-specifications | 2025.9.1 | 0.04 | core |
| sse-starlette | 3.4.8 | 0.04 | core |
| six | 1.17.0 | 0.04 | core |
| annotated-types | 0.8.0 | 0.03 | core |
| zipp | 4.1.0 | 0.02 | core |
| mdurl | 0.1.2 | 0.02 | core |
| sniffio | 1.3.1 | 0.02 | core |
| socksio | 1.0.0 | 0.04 | core (w3-hfix: `httpx[socks]`'s requested extra, now followed) |
| httpx-sse | 0.4.3 | 0.02 | core |
| termcolor | 3.3.0 | 0.02 | core |
| tomli-w | 1.2.0 | 0.01 | core |
| annotated-doc | 0.0.5 | 0.01 | core |

## Release gates (plan D4, lane w4-hd4, 2026-09-28)

Built for real against `8110944532b` (win32-x64, baked with CPython 3.14.5 — the pinned PBS 3.14.7 is not on the build machine); `--verify` of the core and `--verify-pack` both read 0 problems with the licence checks below in them.

**Licences + SBOM — every output, written by the packager.** Each output directory (the core, and each engine pack `<out>-<pack>-pack/`) gets `licenses.json` and `sbom.cdx.json` (`scripts/bundle_licenses.py`):

- `licenses.json` — `{schema: 1, output, target, commit, review_required: [names], components: [...]}`; one component per shipped distribution with `distribution`, `version`, `licence` (PEP 639 `License-Expression`, else a short `License`, else the trove classifiers mapped to SPDX), `licence_files` (output-relative paths — the dist-info's `License-File` entries, else licence-named files in it, else licence-named files its RECORD installs one or two levels deep), `source_url` (the uv.lock wheel URL), `homepage`, `wheel_sha256` (the uv.lock wheel whose tag set equals the dist-info `WHEEL` tags — the one `uv pip install` took), `review`, `review_reasons`, and `embedded` where a copyleft component is compiled in. The core adds `kind: "interpreter"` (CPython from `interpreters.lock.json`: archive URL + SHA-256, `PSF-2.0`, `LICENSE.txt` placed by the installer at the interpreter root, and its embedded OpenSSL / SQLite / libffi / zlib / bzip2 / xz / mpdecimal / expat / vcruntime140) and `kind: "first-party"` (`hermes-agent`, MIT, `app/hermes_agent-0.0.0.dist-info/licenses/LICENSE`, which the packager now copies from `license-files`).
- `sbom.cdx.json` — CycloneDX 1.5 JSON: one `components[]` entry per row (`purl` `pkg:pypi/<name>@<version>`, the interpreter as `pkg:generic/python-build-standalone/cpython@<version>`), licence expression, `SHA-256` hash, distribution/website references, embedded components nested; the serial number is a uuid5 of output + commit, so a rebuild at one commit is byte-stable.
- Verify (both outputs) fails when `licenses.json` names a distribution the output does not ship or misses one it does, when a licence file it cites is not in the output, or when the SBOM's component set differs.

**Flagged for review** (`review: true`; nothing removed — what ships is the closure's decision):

| output | component | why |
|---|---|---|
| core | fal-client 0.13.1 | no licence metadata at all (no expression, field or classifier) and no licence text in the wheel |
| core | firecrawl-anydoc 0.2.4 | MIT, but the wheel carries no licence text |
| speech pack | ctranslate2 4.8.1, flatbuffers 25.12.19, tokenizers 0.23.1 | MIT / Apache-2.0, but the wheels carry no licence text |
| core | cpython (embedded vcruntime140) | Microsoft's redistributable C runtime: confirm the redistribution terms |

**`sherpa-onnx` ships in no output.** It is only in the `wake` / `wake-sherpa` extras, which the profile neither ships (`packaging.extras`) nor packs (`packaging.packs`); `tools.wake_word*` are switched off. Measured: absent from the win32-x64 pool (core + every pack's extras, 107 distributions) and from the exported pins of every target (the union of all markers, 108 pins). There is no espeak-ng in bundled desktop: piper-tts left the speech pack in lane w5-htts (above). `EMBEDDED_COMPONENTS` still names sherpa-onnx, so the day it ships its record is flagged.

**Vulnerability scan** — `python scripts/bundle_vuln_scan.py [--bundle <core> --bundle <pack>] [--target T] [--osv-db PyPI-all.zip] [--json out]`: OSV (online `api.osv.dev`, or offline from OSV's PyPI export), GHSA/PYSEC twins folded into one finding, waivers in `agent_runtime/bundle_profiles/vulnerability-waivers.json` (`id`, `distribution`, `reason`, `expires`; expired covers nothing). Exit 0 clean, 1 an unwaived vulnerability, 2 the scan could not run. **It exits 0** (lane w4-hfix2, core + speech pack built at `49df4f54f77`: 91 pins, 0 unwaived, 0 waived). It exited 1 until then on `httpx2==2.7.0` (CVE-2026-84378, -84379, -84380, -84381, -84382) and `httpcore2==2.7.0` (CVE-2026-84381); `httpx2` is now 2.12.0, which pins `httpcore2==2.12.0` — a fork carry on upstream's pin lines, held by `tests/agent_runtime/test_bundle_vuln_floors.py`.

**Ceilings probe** — `python scripts/bundle_ceilings.py --core <core> --python <target python> [--pack <pack>] [--interpreter-dir <dir>] [--stt-model <dir>] [--json out]` prints `{schema, profile, target, commit, baked, python, python_version, size: {core, core_with_interpreter?, "pack:<name>": {installed_bytes, lzma_bytes, installed_mib, lzma_mib}}, ready: {cold_s, warm_s[], warm_median_s}, stt: {measured, reason?, load_s, first_words_s, final_s, …}}`; exit 1 when serve never reports ready. Measured on this build (baked; LZMA2 preset 9 over a deterministic tar):

| | installed MiB | LZMA MiB |
|---|---:|---:|
| core app + site-packages, baked | 233.22 | 52.08 |
| speech pack, baked | 177.45 | 35.21 |

Ready: cold 2.45 s, warm 1.89 / 1.82 s (empty `HERMES_HOME`, OS file cache not flushed). STT: not measured — no Whisper `tiny.en` (the default tier) snapshot with `model.bin` on this machine (`reason: model_not_present`). The harness skills `agent_runtime.skill_install` installs now ship as a `packaging.resources` entry (`docs/agent-runtime-harness/harness-skills`, 18 files; `--verify` names any missing one). Serve log at `49df4f54f77` (unbaked build): cold start `skill install — 4 package(s), 4 refreshed, 0 failed`, warm start `0 refreshed, 0 failed`; before, every start logged `skill install FAILED — FileNotFoundError`. That unbaked build measured core 141.63 MiB installed / 31.56 MiB LZMA and ready cold 9.93 s / warm 5.61 s (bytecode compiled on first import, so not comparable with the baked rows above, which were not re-taken).

## Tables (generated)

| | distributions | size |
|---|---:|---:|
| Shipped, installed (measured) | 71 | **130.22 MiB** |
| — of which loaded at boot | 25 | 39.21 MiB |
| Shipped, not installed locally (uv.lock wheel bytes, **estimate**) | 20 | ~113.58 MiB |
| **All shipped, as uv.lock wheels (compressed — the installer-ceiling view)** | 91 | **~149.51 MiB** |
| Optional extras reached but not shipped | 15 | 49.76 MiB (direct only) |
| Omitted base distributions | 2 | 51.80 MiB |
| Excludable (reached only by switched-off features) | 25 | 5.73 MiB |

### Shipped, installed (measured)

| distribution | version | declared | pure/native | MiB | loaded at boot |
|---|---|---|---|---:|---|
| annotated-doc | 0.0.5 | requirement | pure | 0.01 | no |
| annotated-types | 0.8.0 | requirement | pure | 0.06 | no |
| anthropic | 0.87.0 | extra anthropic | pure | 1.47 | no |
| anyio | 4.14.2 | base | pure | 1.16 | yes |
| attrs | 26.1.0 | requirement | pure | 0.22 | yes |
| certifi | 2026.5.20 | base | pure | 0.24 | yes |
| cffi | 2.1.1 | requirement | native | 1.05 | yes |
| charset-normalizer | 3.5.1 | requirement | native | 0.81 | yes |
| click | 8.4.2 | requirement | pure | 0.87 | yes |
| colorama | 0.4.6 | requirement | pure | 0.16 | yes |
| concurrent-log-handler | 0.9.29 | base | pure | 0.16 | no |
| croniter | 6.0.0 | base | pure | 0.13 | no |
| cryptography | 50.0.1 (venv 50.0.0) | base | native | 10.56 | no |
| distro | 1.9.0 | requirement | pure | 0.22 | no |
| docstring-parser | 0.18.0 | requirement | pure | 0.07 | no |
| fastapi | 0.133.1 | base | pure | 1.26 | no |
| fire | 0.7.1 | base | pure | 0.82 | no |
| firecrawl-anydoc | 0.2.4 | base | native | 8.30 | no |
| h11 | 0.16.0 | requirement | pure | 0.18 | yes |
| httpcore | 1.0.9 | base | pure | 0.60 | yes |
| httpcore2 | 2.7.0 | requirement | pure | 0.61 | no |
| httpx | 0.28.1 | base | pure | 0.71 | yes |
| httpx-sse | 0.4.3 | requirement | pure | 0.03 | no |
| httpx2 | 2.7.0 | requirement | pure | 0.91 | no |
| idna | 3.19 | requirement | pure | 0.59 | yes |
| jiter | 0.16.0 | base | native | 0.48 | yes |
| jsonschema | 4.26.0 | extra mcp | pure | 1.01 | no |
| jsonschema-specifications | 2025.9.1 | requirement | pure | 0.05 | no |
| markdown-it-py | 4.2.0 | requirement | pure | 0.58 | yes |
| mcp | 2.0.0 | extra mcp | pure | 2.42 | no |
| mcp-types | 2.0.0 | requirement | pure | 0.62 | no |
| mdurl | 0.1.2 | requirement | pure | 0.04 | yes |
| openai | 2.24.0 | base | pure | 7.01 | no |
| opentelemetry-api | 1.39.1 (venv 1.44.0) | requirement | pure | 0.40 | no |
| packaging | 26.0 | base | pure | 0.53 | no |
| pillow | 12.3.0 | base | native | 15.40 | yes |
| portalocker | 3.2.0 (venv 4.1.0) | base | pure | 0.42 | no |
| prompt-toolkit | 3.0.52 | base | pure | 2.91 | no |
| psutil | 8.0.0 (venv 7.2.2) | base | native | 0.80 | yes |
| pycparser | 3.0 | requirement | pure | 0.41 | yes |
| pydantic | 2.13.4 | base | pure | 3.61 | no |
| pydantic-core | 2.46.4 | requirement | native | 5.49 | no |
| pygments | 2.21.0 | requirement | pure | 8.24 | yes |
| pyjwt | 2.13.0 | base | pure | 0.22 | no |
| python-dateutil | 2.9.0.post0 | requirement | pure | 0.71 | no |
| python-dotenv | 1.2.2 | base | pure | 0.21 | yes |
| python-multipart | 0.0.32 | requirement | pure | 0.18 | no |
| pytz | 2026.3.post1 | requirement | pure | 1.03 | no |
| pywin32 | 311 | base | native | 24.43 | no |
| pywinpty | 3.0.5 (venv 2.0.15) | base | native | 5.47 | no |
| pyyaml | 6.0.3 | requirement | native | 0.70 | no |
| referencing | 0.37.0 | requirement | pure | 0.25 | no |
| requests | 2.33.0 | base | pure | 0.40 | yes |
| rich | 14.3.3 | base | pure | 2.47 | yes |
| rpds-py | 2026.6.3 | requirement | native | 0.56 | no |
| ruamel-yaml | 0.18.16 (venv 0.18.17) | base | pure | 1.15 | yes |
| ruamel-yaml-clib | — (venv 0.2.15) | requirement | native | 0.26 | yes |
| six | 1.17.0 | requirement | pure | 0.08 | no |
| sniffio | 1.3.1 | requirement | pure | 0.03 | no |
| snowballstemmer | 3.1.1 | base | pure | 1.74 | no |
| sse-starlette | 3.4.8 | requirement | pure | 0.07 | no |
| starlette | 1.3.1 | base | pure | 0.57 | no |
| termcolor | 3.3.0 | requirement | pure | 0.03 | no |
| tqdm | 4.70.0 | requirement | pure | 0.53 | no |
| truststore | 0.10.4 | base | pure | 0.11 | no |
| typing-extensions | 4.16.0 | requirement | pure | 0.33 | no |
| typing-inspection | 0.4.4 | requirement | pure | 0.09 | no |
| urllib3 | 2.7.0 | requirement | pure | 0.85 | yes |
| uvicorn | 0.41.0 | base | pure | 0.60 | no |
| wcwidth | 0.8.2 | base | pure | 4.20 | no |
| websockets | 15.0.1 | base | native | 1.35 | yes |

### Shipped, not installed locally (estimate: uv.lock wheel bytes)

| distribution | version | MiB (wheel) |
|---|---|---:|
| piper-tts | 1.8.0 | 32.54 |
| av | 18.1.0 | 26.32 |
| ctranslate2 | 4.8.1 | 18.57 |
| onnxruntime | 1.29.0 | 13.69 |
| numpy | 2.4.3 | 11.87 |
| hf-xet | 1.6.0 | 3.85 |
| tokenizers | 0.23.1 | 2.67 |
| faster-whisper | 1.2.1 | 1.07 |
| setuptools | 83.0.0 | 0.96 |
| huggingface-hub | 1.24.0 | 0.74 |
| distlib | 0.4.3 | 0.45 |
| protobuf | 6.33.6 | 0.42 |
| fsspec | 2026.7.0 | 0.20 |
| filelock | 3.32.4 | 0.10 |
| msgpack | 1.2.1 | 0.07 |
| flatbuffers | 25.12.19 | 0.03 |
| pathvalidate | 3.3.1 | 0.02 |
| fal-client | 0.13.1 | 0.02 |
| ptyprocess | 0.7.0 | 0.01 |
| tomli-w | 1.2.0 | 0.01 |

### Optional extras reached but not shipped

| distribution | extras | MiB (installed, else wheel) | first reached via |
|---|---|---:|---|
| agent-client-protocol | acp, all, termux, termux-all | 0.05 | `model_tools → acp_adapter.edit_approval` |
| aiohttp | all, daytona, dingtalk, discord, … | 1.47 | `agent_runtime._upstream_doors → gateway.run → gateway.run_turn` |
| azure-identity | azure-identity | 0.18 | `run_agent → agent.agent_init → agent.azure_identity_adapter` |
| boto3 | bedrock | 0.95 | `agent_runtime.provider_account → hermes_cli.auth_commands` |
| botocore | bedrock | 18.50 | `model_tools → agent.model_metadata → agent.bedrock_adapter` |
| ddgs | ddgs | 0.05 | `agent_runtime._upstream_doors → agent.transports.codex → tools.web_tools` |
| discord-py | discord, messaging | 7.50 | `agent_runtime._upstream_doors → gateway.run → gateway.channel_directory` |
| elevenlabs | tts-premium | 0.50 | `tools.tts_tool_local → tools.tts_tool_delivery → tools.tts_tool_providers` |
| google-auth | all, google, google-chat, termux-all, … | 0.85 | `model_tools → hermes_cli.runtime_provider → agent.vertex_adapter` |
| mistralai | mistral | 1.06 | `tools.transcription_local → tools.transcription_tools → tools.transcription_cloud` |
| pilk | silk | 0.00 | `tools.transcription_local → tools.transcription_audio` |
| pip | kittentts | 10.51 | `cron.scheduler → cron.scheduler_script → hermes_cli._launchers` |
| python-telegram-bot | messaging, telegram, termux, termux-all | 6.75 | `cron.scheduler → cron.scheduler_delivery → tools.send_message_tool → tools.send_message_senders` |
| qrcode | dingtalk, feishu, messaging | 0.42 | `run_agent → hermes_cli.profiles → hermes_cli.gateway → hermes_cli.setup_platforms → hermes_cli.telegram_managed_bot` |
| soundfile | kittentts | 0.97 | `tools.tts_tool_local` |

### Omitted base distributions

| distribution | MiB | what degrades |
|---|---:|---|
| nemo-relay | 24.25 | bundled runs NoopRelayRuntime (owner ruling 2026-09-28) — no managed execution, no Relay plugins, no shared metrics |
| pillow-heif | 27.55 | (owner-confirmed 2026-09-28; the Launcher handles image formats) HEIC/HEIF images (iPhone photos) cannot be decoded — vision_analyze returns its no-decoder message and image routing skips the image; AVIF still decodes (native in Pillow 12) |

### Excludable

| distribution | version | MiB |
|---|---|---:|
| aiohappyeyeballs | 2.7.1 | 0.04 |
| aiohttp | 3.14.3 | 1.47 |
| aiohttp-socks | 0.11.0 | 0.00 |
| aiosignal | 1.4.0 | 0.02 |
| aiosqlite | 0.22.1 | 0.00 |
| asyncpg | 0.31.0 | 0.00 |
| davey | 0.1.6 | 2.03 |
| frozenlist | 1.8.0 | 0.11 |
| iniconfig | 2.3.0 | 0.00 |
| markdown | 3.10.2 | 0.77 |
| mautrix | 0.21.1 | 0.00 |
| multidict | 6.7.1 | 0.13 |
| pluggy | 1.6.0 | 0.00 |
| propcache | 0.5.2 | 0.10 |
| pynacl | 1.6.2 (venv 1.5.0) | 0.79 |
| pytest | 9.1.1 | 0.00 |
| pytest-asyncio | 1.3.0 | 0.00 |
| python-socks | 2.8.2 | 0.00 |
| regex | 2026.9.10 | 0.00 |
| resvg-py | 0.4.0 | 0.00 |
| safetensors | 0.8.0 | 0.00 |
| shellingham | 1.5.4 | 0.00 |
| transformers | 5.17.0 | 0.00 |
| typer | 0.27.1 | 0.00 |
| yarl | 1.24.5 | 0.29 |
