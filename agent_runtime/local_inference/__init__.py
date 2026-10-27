"""Small local ONNX models on the speech pack's onnxruntime: text embeddings and zero-shot image tags.

``runtime.embed.texts`` (bge-small-en-v1.5, int8) and ``runtime.vision.tag`` (CLIP ViT-B/32,
int8). Contract: ``docs/agent-runtime-harness/runtime-local-inference-methods.md``. Plans: launcher
``docs/messaging/planned/LOCAL_SEMANTIC_INDEX_2026-10-27.md`` S2 and
``docs/posts/planned/CLIENT_TAGGER_OPTIONAL_2026-10-27.md`` S0.

=============  ======  ========================================================
module         layer   owns
=============  ======  ========================================================
models         models  the model table (files, dims), ``LocalInferenceRefused``,
                       folder resolution and inspection (no loader)
wordpiece      models  the BERT WordPiece tokenizer bge reads (pure Python)
clip_bpe       models  CLIP's byte-level BPE tokenizer (pure Python)
runners        stores  the onnxruntime sessions (numpy, Pillow) behind the seam
service        lanes   params, the loaded-model and label-embedding caches,
                       scoring, the f32le codec; the process-wide service
=============  ======  ========================================================

Nothing here downloads: the Launcher installs a model folder and passes ``models_dir``.
"""

from __future__ import annotations

__layer__ = "lanes"
