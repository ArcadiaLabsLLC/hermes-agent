"""The local-inference model table and model-folder inspection. No loader, no network.

A model is a ROW in :data:`EMBED_MODELS` or :data:`VISION_MODELS`: its id (what a client passes as
``model``), the files its folder must hold (the names the Launcher's catalog entry places them
under), its output dimension and its token limit. The folder is ``<models_dir>/<model>``.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__layer__ = "models"

__all__ = [
    "EMBED_MODELS",
    "ENGINE_MODULES",
    "VISION_MODELS",
    "LocalInferenceRefused",
    "LocalModelSpec",
    "absent_engine_modules",
    "model_folder",
]

#: What the onnxruntime runners import; both are the speech pack's (``speech-tts`` extra).
ENGINE_MODULES = ("onnxruntime", "numpy")


class LocalInferenceRefused(Exception):
    """A request the service will not run. ``code`` is the error family, ``reason`` the branch."""

    def __init__(self, reason: str, code: str = "invalid_params", message: str = "", **data: Any) -> None:
        super().__init__(message or reason)
        self.reason, self.code, self.data = reason, code, data


@dataclass(frozen=True)
class LocalModelSpec:
    """One installable local model: the folder's files, the vector width, the token limit.

    ``kind`` is the :data:`agent_runtime.model_admission.KINDS` entry its load reserves under."""

    model: str
    kind: str
    runner: str
    files: tuple[str, ...]
    dim: int
    max_tokens: int


#: ``runtime.embed.texts`` models. bge-small-en-v1.5 is the backend's ``DEFAULT_EMBEDDING_MODEL``;
#: the files are Xenova's transformers.js int8 export (``onnx/model_quantized.onnx``, ``vocab.txt``).
EMBED_MODELS: dict[str, LocalModelSpec] = {
    "bge-small-en-v1.5": LocalModelSpec(
        model="bge-small-en-v1.5", kind="embed", runner="bert_cls", files=("model_quantized.onnx", "vocab.txt"),
        dim=384, max_tokens=512),
}

#: ``runtime.vision.tag`` models: Xenova's transformers.js int8 export of openai/clip-vit-base-patch32
#: (``onnx/text_model_quantized.onnx``, ``onnx/vision_model_quantized.onnx``, ``vocab.json``, ``merges.txt``).
VISION_MODELS: dict[str, LocalModelSpec] = {
    "clip-vit-base-patch32": LocalModelSpec(
        model="clip-vit-base-patch32", kind="vision", runner="clip",
        files=("text_model_quantized.onnx", "vision_model_quantized.onnx", "vocab.json", "merges.txt"),
        dim=512, max_tokens=77),
}


def _models_dir(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise LocalInferenceRefused("models_dir_invalid", message="models_dir must be an absolute path")
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise LocalInferenceRefused("models_dir_invalid", message="models_dir must be an absolute path")
    return path


def model_folder(params: dict, table: dict[str, LocalModelSpec]) -> tuple[LocalModelSpec, Path]:
    """The spec and the complete, loadable folder ``params`` name, or a typed refusal.

    ``model_unknown`` (not a table row), ``model_missing`` (no folder), ``model_partial`` (files
    missing, named in ``missing``). Whether the engine imports is :func:`absent_engine_modules`."""
    name = params.get("model")
    spec = table.get(name) if isinstance(name, str) else None
    if spec is None:
        raise LocalInferenceRefused("model_unknown", message=f"model must be one of {sorted(table)}",
                                    models=sorted(table))
    folder = _models_dir(params.get("models_dir")) / spec.model
    if not folder.is_dir():
        raise LocalInferenceRefused("model_missing", "not_found", f"{spec.model} is not installed",
                                    model_path=str(folder))
    missing = [file for file in spec.files if not (folder / file).is_file()]
    if missing:
        raise LocalInferenceRefused("model_partial", "not_found", f"{spec.model} is incomplete",
                                    model_path=str(folder), missing=missing)
    return spec, folder


def absent_engine_modules() -> list[str]:
    """The :data:`ENGINE_MODULES` this interpreter cannot import (the speech pack is absent)."""
    return [module for module in ENGINE_MODULES if importlib.util.find_spec(module) is None]
