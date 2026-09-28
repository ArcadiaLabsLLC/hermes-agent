# Bundled desktop — import closure and package list (2026-09-28)

What the **bundled-desktop** profile (`agent_runtime/bundle_profiles/bundled-desktop.yaml`) ships, per the standing rule *bundle only what is needed* (launcher `EterniaLauncher/docs/embedded_hermes/planned/PROFILE_MATRIX_2026-09-28.md`). Regenerate (the tables below are the `--markdown` output, pasted unedited):

```
python scripts/bundle_profile_closure.py --profile bundled-desktop --json <out.json> --markdown <out.md>
```

The script exits 1 (`REFUSED: …`) when an omitted distribution is imported unguarded, when an omitted distribution is a requirement of a shipped one, or when `packaging.extras` names no pyproject extra.

## Method, and which numbers are estimates

- **Static walk** (`ast`): every `import`, module-level AND inside functions, plus `importlib.import_module("literal")` calls (this is how `agent.relay_runtime` loads `nemo_relay`, which the first walk missed), from the manifest's `packaging.roots`; the walk never follows an import into `packaging.switched_off_modules`. Lazy imports count, so "reached" is an **upper bound**.
- **What ships** is decided by the distribution's declaration in `pyproject.toml`, markers evaluated for the bundle target (win_amd64, CPython 3.14): a **base** dependency ships unless `packaging.omitted_distributions` drops it (refused unless every import site in the kept modules is guarded by `try`/`suppress` catching `ImportError`); an **optional extra** ships only when `packaging.extras` names one of its extras — full Hermes installs extras lazily and their import sites tolerate absence, and the profile turns lazy installs off, so an unshipped extra is an unavailable feature, never a download; an undeclared distribution the walk reaches ships and is listed; every shipped distribution's requirements ship with it.
- **Pinned** = a switched-off module a kept module imports at module level, unguarded: it loads whatever the config says, so its module-level imports count. A guarded module-level import is already a seam.
- **Instrumented boot probe**: importing the roots in a fresh interpreter and reading `sys.modules`. "Boot" = loaded at import time (a **lower bound**).
- **Excludable** = reached only through a switched-off module.
- **Measured** sizes: on-disk bytes of each installed distribution's RECORD files in the live Hermes venv (CPython 3.12.14, win_amd64). **Estimated**: distributions the live venv does not have (the speech stack) are sized by their uv.lock wheel. **Wheels (compressed)**: every shipped distribution's uv.lock wheel (cp314, else cp312/abi3 win_amd64, else `none-any`) — the number comparable to the installer ceiling.

## Before → after (lane w2-hslim)

| | before | after |
|---|---:|---:|
| distributions shipped | 121 (89 measured + 32 estimated) | 92 (72 + 20) |
| installed, measured | 222.3 MiB | 154.5 MiB |
| not installed, wheel estimate | ~124.6 MiB | ~113.6 MiB |
| **all shipped, as compressed wheels** | ~192.8 MiB | **~158.7 MiB** |
| — core only (no speech extras / speech roots) | — | **~45.6 MiB** |
| boot set (third-party loaded at import) | 26 dists, 39.6 MiB | 25 dists, 39.2 MiB |
| first-party modules kept by the walk | 2161 | 2135 |
| pinned switched-off modules | 12 | 9 |

What moved it:

- **Extras are not base.** `discord-py`, `python-telegram-bot`, `boto3`/`botocore` (Bedrock), `google-auth` (Vertex), `azure-identity`, `mistralai`, `elevenlabs`, `ddgs`, `qrcode`, `pip`, `soundfile`, `pilk`, `agent-client-protocol`, `aiohttp` are optional extras the walk reaches; the profile ships only `anthropic`, `mcp`, `fal`, `piper`, `stt-whisper`. Bedrock, Vertex, Azure identity and Mistral are therefore **unavailable** in bundled Hermes (their providers raise their own "install the extra" error; lazy installs are off). The messaging SDKs reached via `cron.scheduler → cron.scheduler_delivery → tools.send_message_tool → tools.send_message_senders` and `gateway.run → gateway.channel_directory` are extras, so they no longer count.
- **`pillow-heif` omitted** (27.6 MiB installed): both import sites (`agent.image_routing`, `tools.vision_tools_image_prep`) are guarded; HEIC/HEIF photos cannot be decoded, AVIF still decodes (native in Pillow 12).
- **Switched off, not packaged** (matrix "—"): voice mode glue `hermes_cli.voice`; checkout-bound `gateway.code_skew`, `hermes_cli.update_cmd*` / `update_completion` / `update_inventory` / `worktree_cmd` / `relay_plugin_migrate`; dev tooling `agent_runtime.doctor_extensions`. `cron.scheduler → gateway.code_skew → hermes_cli.main` is cut at `code_skew` (both cron call sites are `try/except Exception → None`, the right answer for a wheel).
- **Seam:** `hermes_cli.web_server_config` imports `tools.wake_word._PROVIDER_PREFERENCE` guarded, so the dashboard schema loads without wake word (offers only "auto").
- **Tree corrections:** `hermes_cli.web_routers.local_models` is no longer listed as switched off — the profile's route gate refuses its download routes and requires them mounted, so it ships. `hermes_cli.worktree_ops` (kanban's worktree workspaces import it) and `agent_runtime.harness_doctor` (the harness parser registers `harness doctor` at import) stay packaged.

## What stayed, and why

- **Speech (~113 MiB compressed)**: `piper-tts` 32.5 (all-language espeak data), `av` 26.3 (PyAV, via faster-whisper), `ctranslate2` 18.6, `onnxruntime` 13.7, `numpy` 11.9, `hf-xet` 3.9, `tokenizers` 2.7. Owner ruling D4 expects ~25–35 MB once PyAV and non-English Piper data are dropped — that is the speech lane's work, not an import seam.
- **`nemo-relay`** (9.2 MiB wheel, 24.3 installed): loaded by the agent core on every turn (`agent.relay_runtime._load_nemo_relay`, via `importlib`); a `NoopRelayRuntime` fallback exists (managed execution and Relay plugins off). Dropping it is an owner decision, not a packaging fact.
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

All read through one helper, `hermes_cli.config.config_switch`. The profile also sets the existing `auth.adopt_external_logins: false` (Claude Code / Codex CLI logins never borrowed); **Qwen OAuth is not covered by that key** — its only token store is the Qwen CLI's own file. Still unswitched: `agent_runtime.repo_context` (affected-repo resolution and harness worktree inventory consult git).

## Tables (generated)

| | distributions | size |
|---|---:|---:|
| Shipped, installed (measured) | 72 | **154.46 MiB** |
| — of which loaded at boot | 25 | 39.21 MiB |
| Shipped, not installed locally (uv.lock wheel bytes, **estimate**) | 20 | ~113.58 MiB |
| **All shipped, as uv.lock wheels (compressed — the installer-ceiling view)** | 92 | **~158.73 MiB** |
| Optional extras reached but not shipped | 15 | 49.76 MiB (direct only) |
| Omitted base distributions | 1 | 27.55 MiB |
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
| nemo-relay | 0.8.4 | base | native | 24.25 | no |
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
| pillow-heif | 27.55 | HEIC/HEIF images (iPhone photos) cannot be decoded — vision_analyze returns its no-decoder message and image routing skips the image; AVIF still decodes (native in Pillow 12) |

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
