# `runtime.embed.texts` and `runtime.vision.tag` — method contract

Two small local ONNX models on the onnxruntime the speech pack already ships: sentence
embeddings for the Launcher's local semantic index, and zero-shot image tags for the composer's
optional tag suggestions. Registered by `agent_runtime/serve_rpc/local_inference.py`; the work is
`agent_runtime/local_inference/` (its `__init__` carries the module map). Frames, error codes and
the manifest follow [03 — transport and wire](03-transport-and-wire.md). Plans: launcher
`docs/messaging/planned/LOCAL_SEMANTIC_INDEX_2026-10-27.md` S2 (row `RT-LOCAL-EMBED-TEXTS`) and
`docs/posts/planned/CLIENT_TAGGER_OPTIONAL_2026-10-27.md` S0 (row `RT-LOCAL-IMAGE-TAG`).

Every success result carries `contract: 1`. Adding the methods grows the manifest set without
moving `RPC_CONTRACT_VERSION`.

## Models: an installed folder, never a download

A model is a row of `EMBED_MODELS` / `VISION_MODELS` (`agent_runtime/local_inference/models.py`).
The client passes its id as `model` and the absolute `models_dir` it installed into; the folder
is `<models_dir>/<model>`, **flat**, with exactly these names (the Launcher's catalog entry
places each file under them):

| `model` | runner | files | dim |
|---|---|---|---|
| `bge-small-en-v1.5` | WordPiece ids, `[CLS]` row of `last_hidden_state`, L2-normalised | `model_quantized.onnx`, `vocab.txt` | 384 |
| `clip-vit-base-patch32` | CLIP BPE text embeds per label, image embeds per image, both L2-normalised | `text_model_quantized.onnx`, `vision_model_quantized.onnx`, `vocab.json`, `merges.txt` | 512 |

Both are Xenova's transformers.js int8 exports (the repos keep the `.onnx` files under `onnx/`;
the folder here is flat). Sizes and SHA-256 are pinned by the Launcher's catalog entry, read from
the Hugging Face API, not here. The tokenizers are pure Python
(`local_inference/wordpiece.py`, `local_inference/clip_bpe.py`): the pack adds no `tokenizers`
or `regex` wheel. The image is decoded by Pillow (a core dependency), resized on its short side
to 224 bicubic, centre-cropped and normalised with CLIP's mean and standard deviation.

Nothing is fetched: a missing folder is `model_missing`, a folder short of a file is
`model_partial` with `missing` naming the files, and an interpreter without onnxruntime / numpy
(the speech pack not installed) is `engine_missing` with `modules`. A runner that fails to build
is `load_failed` with `error_class`.

At most two runners stay loaded (least recently used dropped). **They are not reserved through
`runtime.admission.*`** — its `KINDS` are `stt`, `tts`, `llm` — and that gap is the row
`RT-LOCAL-INFERENCE-ADMISSION` in `Harness_Brain/20 — Active Initiatives/runtime-queue.md`.

## Methods

| method | tier | params | result |
|---|---|---|---|
| `runtime.embed.texts` | console | `model`, `models_dir`, `texts` | `{contract, model, dim, encoding, vectors}` |
| `runtime.vision.tag` | console | `model`, `models_dir`, `image`, `labels`, `top_k?` | `{contract, model, scores}` |

**`runtime.embed.texts`.** `texts` is 1–64 strings of at most 16 000 characters (the tokenizer
keeps the first 512 tokens). `encoding` is `f32le_base64`: `vectors[i]` is the base64 of `dim`
little-endian float32 values for `texts[i]`, unit length, so a dot product is the cosine. bge
v1.5 needs no query instruction; a client that wants one prepends it to the text.

**`runtime.vision.tag`.** `image` is base64 of at most 2 MiB decoded (the composer resizes
first), a picture Pillow can read of at most 50 000 000 pixels. `labels` is 1–512 distinct,
printable strings of at most 64 characters — the vocabulary; nothing outside it is ever
answered. Each label is embedded as `a photo of <label>.`, and those text embeddings are cached
per (model, folder, SHA-256 of the prompt and the ordered labels) for the last eight
vocabularies, so a repeat call embeds only the image. `scores` is the `top_k` (default
`min(5, len(labels))`) labels by softmax over `100 × cosine` (CLIP's logit scale), highest first:
`[{label, score}]`, `score` in 0–1 summing to 1 over the whole vocabulary. Advisory only — the
backend's safety pass stays authoritative.

## Refusals

| code | reasons |
|---|---|
| `-32602` invalid params | `model_unknown` (+ `models`), `models_dir_invalid`, `texts_empty`, `texts_too_many`, `text_invalid`, `text_too_long`, `labels_empty`, `labels_too_many`, `label_invalid`, `label_too_long`, `labels_duplicate`, `top_k_invalid`, `image_invalid`, `image_too_large`, `image_unreadable` |
| `4001` not found | `model_missing`, `model_partial` (+ `missing`), `engine_missing` (+ `modules`) — each with `model_path` where one exists |
| `-32000` handler failed | `load_failed` (+ `error_class`), `handler_failed` (+ `error_class`) |

Both replies are deferred onto the transport's worker lane when it has one; inference runs one
call at a time per process.
