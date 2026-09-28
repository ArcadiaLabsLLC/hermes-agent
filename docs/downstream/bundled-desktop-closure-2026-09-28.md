# Bundled desktop — import closure and package list (2026-09-28)

What the **bundled-desktop** profile (`agent_runtime/bundle_profiles/bundled-desktop.yaml`) pulls in, per the standing rule *bundle only what is needed* (launcher `EterniaLauncher/docs/embedded_hermes/planned/PROFILE_MATRIX_2026-09-28.md`). Regenerate with:

```
python scripts/bundle_profile_closure.py --profile bundled-desktop --json <out.json>
```

## Method, and which numbers are estimates

- **Static walk** (`ast`): every `import`, module-level AND inside functions, from the manifest's `packaging.roots`; the walk never follows an import into `packaging.switched_off_modules`. Lazy imports count, so "needed" is an **upper bound** — the safe direction for a bundle.
- **Instrumented boot probe**: importing the roots in a fresh interpreter and reading `sys.modules`. "Boot" = loaded at import time (a **lower bound**).
- **Excludable** = reached only through a switched-off module (the same walk with the switched-off modules as extra roots, minus the needed set).
- **Measured** sizes: on-disk bytes of each distribution's RECORD files in the live venv `X:\Eternia\.hermes\venvs\hermes-agent` (CPython 3.12.14, win_amd64). Versions: `uv.lock` (venv version in brackets where it differs).
- **Estimated** sizes: distributions the walk needs but the live venv does not have installed (optional extras — the speech stack among them) are sized by their **uv.lock wheel** (cp312/abi3 win_amd64, else `none-any`) — compressed bytes; installed size is typically larger.

## Totals

| | distributions | size |
|---|---:|---:|
| Needed, installed (measured) | 89 | **222.3 MiB** |
| — of which loaded at boot | 26 | 39.6 MiB |
| Needed, not installed locally (uv.lock wheel bytes, **estimate**) | 32 | ~124.6 MiB |
| **Needed total (measured + estimate)** | 121 | **~347 MiB** |
| Excludable (reached only by switched-off features) | 5 | 8.5 MiB |
| Live venv `site-packages`, for scale | 111 | 289 MiB |

The boot probe also loaded `brotlicffi` (an optional `try: import` inside httpx), which the static walk does not attribute.

## Largest ten (measured)

| # | distribution | version | pure/native | MiB |
|---:|---|---|---|---:|
| 1 | pillow-heif | 1.6.0 | native | 27.55 |
| 2 | pywin32 | 311 | native | 24.43 |
| 3 | nemo-relay | 0.8.4 | native | 24.25 |
| 4 | botocore | 1.42.97 | pure | 18.50 |
| 5 | pillow | 12.3.0 | native | 15.40 |
| 6 | cryptography | 50.0.1 | native | 10.56 |
| 7 | pip | 26.2.1 | pure | 10.51 |
| 8 | pygments | 2.21.0 | pure | 8.24 |
| 9 | discord-py | 2.7.1 | native | 7.50 |
| 10 | openai | 2.24.0 | pure | 7.01 |

Largest not-installed (estimate, wheel bytes): piper-tts 32.5, av 26.3, ctranslate2 18.3, onnxruntime 13.4, numpy 11.8 MiB — the speech service (faster-whisper + Piper), which the matrix turns **on** for bundled desktop.

## Excludable

| distribution | version | pure/native | MiB |
|---|---|---|---:|
| davey | 0.1.6 | native | 2.03 |
| markdown | 3.10.2 | pure | 0.77 |
| pynacl | 1.6.2 (venv 1.5.0) | native | 0.79 |
| slack-bolt | 1.30.0 | pure | 1.57 |
| slack-sdk | 3.44.1 | pure | 3.36 |

## Why the excludable list is short — switched-off features are not import-isolated

The manifest switches features off through configuration, but on-feature code reaches off-feature modules, so the walk keeps their dependencies:

- **Pinned modules** — switched-off modules a kept module imports at MODULE level, so they load whatever the config says: `tools.terminal_tool`, `tools.terminal_tool_lifecycle`, `tools.environments.{docker,local}`, `gateway.platforms.{base,_shared,base_exec_approval,event,helpers}`, `tools.voice_mode`, `tools.wake_word`, `hermes_cli.web_routers.local_models` (the last via `hermes_cli.web_server`).
- **Messaging SDKs stay "needed"** through on-feature lazy imports: `discord-py` via `agent_runtime._upstream_doors → gateway.run → gateway.channel_directory`; `python-telegram-bot` via `cron.scheduler → cron.scheduler_delivery → tools.send_message_tool → tools.send_message_senders`; `qrcode`/`pip` via `agent_runtime.doctor_extensions → hermes_cli.gateway → …`.
- **The whole CLI is reached**: `cron.scheduler → gateway.code_skew → hermes_cli.main` drags `fastapi`, `uvicorn`, `nemo-relay` (24 MiB, via `hermes_cli.subcommands.migrate → hermes_cli.relay_plugin_migrate`).
- **Bedrock** (`boto3`/`botocore`, 19.8 MiB) via `model_tools → agent.model_metadata → agent.bedrock_adapter`.

Turning these into excludables needs import seams (an off feature's module is only imported when the feature is on), not more manifest entries.

## Needed, installed (measured)

| distribution | version | pure/native | MiB | loaded at boot |
|---|---|---|---:|---|
| aiohappyeyeballs | 2.7.1 | pure | 0.04 | no |
| aiohttp | 3.14.3 | native | 1.47 | no |
| aiosignal | 1.4.0 | pure | 0.02 | no |
| annotated-doc | 0.0.5 | pure | 0.01 | no |
| annotated-types | 0.8.0 | pure | 0.06 | no |
| anthropic | 0.87.0 | pure | 1.47 | no |
| anyio | 4.14.2 | pure | 1.16 | yes |
| attrs | 26.1.0 | pure | 0.22 | yes |
| boto3 | 1.42.89 | pure | 0.95 | no |
| botocore | 1.42.97 | pure | 18.50 | no |
| certifi | 2026.5.20 | pure | 0.24 | yes |
| cffi | 2.1.1 | native | 1.05 | yes |
| charset-normalizer | 3.5.1 | native | 0.81 | yes |
| click | 8.4.2 | pure | 0.87 | yes |
| colorama | 0.4.6 | pure | 0.16 | yes |
| concurrent-log-handler | 0.9.29 | pure | 0.16 | no |
| croniter | 6.0.0 | pure | 0.13 | no |
| cryptography | 50.0.1 (venv 50.0.0) | native | 10.56 | no |
| discord-py | 2.7.1 | native | 7.50 | no |
| distro | 1.9.0 | pure | 0.22 | no |
| docstring-parser | 0.18.0 | pure | 0.07 | no |
| fastapi | 0.133.1 | pure | 1.26 | no |
| fire | 0.7.1 | pure | 0.82 | no |
| frozenlist | 1.8.0 | native | 0.11 | no |
| google-auth | 2.55.1 | pure | 0.85 | no |
| h11 | 0.16.0 | pure | 0.18 | yes |
| httpcore | 1.0.9 | pure | 0.60 | yes |
| httpcore2 | 2.7.0 | pure | 0.61 | no |
| httpx | 0.28.1 | pure | 0.71 | yes |
| httpx2 | 2.7.0 | pure | 0.91 | no |
| idna | 3.19 | pure | 0.59 | yes |
| jiter | 0.16.0 | native | 0.48 | yes |
| jmespath | 1.1.0 | pure | 0.07 | no |
| jsonschema | 4.26.0 | pure | 1.01 | no |
| jsonschema-specifications | 2025.9.1 | pure | 0.05 | no |
| markdown-it-py | 4.2.0 | pure | 0.58 | yes |
| mcp | 2.0.0 | pure | 2.42 | no |
| mcp-types | 2.0.0 | pure | 0.62 | no |
| mdurl | 0.1.2 | pure | 0.04 | yes |
| multidict | 6.7.1 | native | 0.13 | no |
| nemo-relay | 0.8.4 | native | 24.25 | no |
| openai | 2.24.0 | pure | 7.01 | no |
| opentelemetry-api | 1.39.1 (venv 1.44.0) | pure | 0.40 | no |
| packaging | 26.0 | pure | 0.53 | no |
| pillow | 12.3.0 | native | 15.40 | yes |
| pillow-heif | 1.6.0 (venv 1.7.0) | native | 27.55 | no |
| pip | 26.2.1 | pure | 10.51 | no |
| portalocker | 3.2.0 (venv 4.1.0) | pure | 0.42 | no |
| prompt-toolkit | 3.0.52 | pure | 2.91 | no |
| propcache | 0.5.2 | native | 0.10 | no |
| psutil | 8.0.0 (venv 7.2.2) | native | 0.80 | yes |
| pyasn1 | 0.6.4 | pure | 0.37 | no |
| pyasn1-modules | 0.4.2 | pure | 0.70 | no |
| pycparser | 3.0 | pure | 0.41 | yes |
| pydantic | 2.13.4 | pure | 3.61 | no |
| pydantic-core | 2.46.4 | native | 5.49 | no |
| pygments | 2.21.0 | pure | 8.24 | yes |
| pyjwt | 2.13.0 | pure | 0.22 | no |
| pypng | 0.20220715.0 | pure | 0.24 | no |
| python-dateutil | 2.9.0.post0 | pure | 0.71 | no |
| python-dotenv | 1.2.2 | pure | 0.21 | yes |
| python-multipart | 0.0.32 | pure | 0.18 | no |
| python-telegram-bot | 22.8 | pure | 6.75 | no |
| pytz | 2026.3.post1 | pure | 1.03 | no |
| pywin32 | 311 | native | 24.43 | no |
| pywinpty | 3.0.5 (venv 2.0.15) | native | 5.47 | no |
| qrcode | 7.4.2 | pure | 0.42 | no |
| referencing | 0.37.0 | pure | 0.25 | no |
| requests | 2.33.0 | pure | 0.40 | yes |
| rich | 14.3.3 | pure | 2.47 | yes |
| rpds-py | 2026.6.3 | native | 0.56 | no |
| ruamel-yaml | 0.18.16 (venv 0.18.17) | pure | 1.15 | yes |
| ruamel-yaml-clib | — (venv 0.2.15) | native | 0.26 | yes |
| s3transfer | 0.16.1 | pure | 0.31 | no |
| six | 1.17.0 | pure | 0.08 | no |
| sniffio | 1.3.1 | pure | 0.03 | no |
| snowballstemmer | 3.1.1 | pure | 1.74 | no |
| sse-starlette | 3.4.8 | pure | 0.07 | no |
| starlette | 1.3.1 | pure | 0.57 | no |
| termcolor | 3.3.0 | pure | 0.03 | no |
| tqdm | 4.70.0 | pure | 0.53 | no |
| truststore | 0.10.4 | pure | 0.11 | no |
| typing-extensions | 4.16.0 | pure | 0.33 | yes |
| typing-inspection | 0.4.4 | pure | 0.09 | no |
| urllib3 | 2.7.0 | pure | 0.85 | yes |
| uvicorn | 0.41.0 | pure | 0.60 | no |
| wcwidth | 0.8.2 | pure | 4.20 | no |
| websockets | 15.0.1 | native | 1.35 | yes |
| yarl | 1.24.5 | native | 0.29 | no |

## Needed, not installed locally (estimate: uv.lock wheel bytes)

| distribution | version | MiB (wheel) |
|---|---|---:|
| piper-tts | 1.8.0 | 32.54 |
| av | 18.1.0 | 26.32 |
| ctranslate2 | 4.8.1 | 18.33 |
| onnxruntime | 1.29.0 | 13.35 |
| numpy | 2.4.3 | 11.75 |
| primp | 2.0.0 | 4.98 |
| hf-xet | 1.6.0 | 3.85 |
| lxml | 6.1.2 | 3.82 |
| tokenizers | 0.23.1 | 2.67 |
| faster-whisper | 1.2.1 | 1.07 |
| mistralai | 2.4.8 | 1.06 |
| soundfile | 0.14.0 | 0.97 |
| setuptools | 83.0.0 | 0.96 |
| huggingface-hub | 1.24.0 | 0.74 |
| elevenlabs | 1.59.0 | 0.50 |
| distlib | 0.4.3 | 0.45 |
| protobuf | 6.33.6 | 0.42 |
| opentelemetry-semantic-conventions | 0.60b1 | 0.21 |
| fsspec | 2026.7.0 | 0.20 |
| pyyaml | 6.0.3 | 0.15 |
| filelock | 3.32.4 | 0.10 |
| msgpack | 1.2.1 | 0.07 |
| ddgs | 9.16.0 | 0.05 |
| flatbuffers | 25.12.19 | 0.03 |
| pathvalidate | 3.3.1 | 0.02 |
| fal-client | 0.13.1 | 0.02 |
| jsonpath-python | 1.1.6 | 0.01 |
| ptyprocess | 0.7.0 | 0.01 |
| httpx-sse | 0.4.3 | 0.01 |
| tomli-w | 1.2.0 | 0.01 |
| eval-type-backport | 0.4.0 | 0.01 |
| pilk | 0.2.4 | 0.00 |
