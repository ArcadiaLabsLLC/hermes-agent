"""The onnxruntime sessions behind the local-inference seam (numpy and Pillow, imported lazily).

Each runner is built from a complete model folder (:func:`agent_runtime.local_inference.models.model_folder`)
and answers plain Python lists, so the service above it never imports numpy and tests replace a
runner with a fake. CPU only, like the speech pack's other engines.

* :class:`BertClsEmbedder` — bge-small-en-v1.5: WordPiece ids, the ``[CLS]`` row of
  ``last_hidden_state``, L2-normalised (bge's own pooling).
* :class:`ClipZeroShot` — CLIP ViT-B/32: ``text_embeds`` per label and ``image_embeds`` per image,
  each L2-normalised; the image is resized on its short side to 224 (bicubic), centre-cropped and
  normalised with CLIP's mean and standard deviation, as ``CLIPImageProcessor`` does.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Callable

from agent_runtime.local_inference.clip_bpe import ClipBpe
from agent_runtime.local_inference.models import LocalModelSpec
from agent_runtime.local_inference.wordpiece import WordPiece

__layer__ = "stores"

__all__ = ["RUNNERS", "BertClsEmbedder", "ClipZeroShot", "load_runner"]

_CLIP_SIZE = 224
_CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
_CLIP_STD = (0.26862954, 0.26130258, 0.27577711)


def _onnx_session(path: Path) -> Any:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.log_severity_level = 3
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def _padded_ids(rows: list[list[int]], pad: int) -> tuple[Any, Any]:
    import numpy as np

    width = max(len(row) for row in rows)
    ids = np.full((len(rows), width), pad, dtype=np.int64)
    mask = np.zeros((len(rows), width), dtype=np.int64)
    for index, row in enumerate(rows):
        ids[index, : len(row)] = row
        mask[index, : len(row)] = 1
    return ids, mask


def _unit_rows(matrix: Any) -> list[list[float]]:
    import numpy as np

    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.maximum(norms, 1e-12)).tolist()


def _feeds(session: Any, available: dict[str, Any]) -> dict[str, Any]:
    """Only the inputs the exported graph declares (exports differ on ``token_type_ids`` / masks)."""
    return {item.name: available[item.name] for item in session.get_inputs() if item.name in available}


class BertClsEmbedder:
    def __init__(self, spec: LocalModelSpec, folder: Path) -> None:
        self.tokenizer = WordPiece.from_file(folder / "vocab.txt", max_tokens=spec.max_tokens)
        self.session = _onnx_session(folder / "model_quantized.onnx")

    def embed(self, texts: list[str]) -> list[list[float]]:
        import numpy as np

        ids, mask = _padded_ids([self.tokenizer.encode(text) for text in texts], self.tokenizer.pad)
        feeds = _feeds(self.session, {"input_ids": ids, "attention_mask": mask,
                                      "token_type_ids": np.zeros_like(ids)})
        hidden = self.session.run(None, feeds)[0]
        return _unit_rows(hidden[:, 0, :])


class ClipZeroShot:
    def __init__(self, spec: LocalModelSpec, folder: Path) -> None:
        self.tokenizer = ClipBpe.from_files(folder / "vocab.json", folder / "merges.txt", max_tokens=spec.max_tokens)
        self.text_session = _onnx_session(folder / "text_model_quantized.onnx")
        self.vision_session = _onnx_session(folder / "vision_model_quantized.onnx")

    @staticmethod
    def _named(session: Any, outputs: list[Any], name: str) -> Any:
        names = [item.name for item in session.get_outputs()]
        return outputs[names.index(name)] if name in names else outputs[0]

    def text_embeds(self, texts: list[str]) -> list[list[float]]:
        ids, mask = _padded_ids([self.tokenizer.encode(text) for text in texts], self.tokenizer.end)
        outputs = self.text_session.run(None, _feeds(self.text_session, {"input_ids": ids, "attention_mask": mask}))
        return _unit_rows(self._named(self.text_session, outputs, "text_embeds"))

    def image_embeds(self, image: bytes) -> list[float]:
        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(image)) as opened:
            picture = opened.convert("RGB")
        width, height = picture.size
        scale = _CLIP_SIZE / min(width, height)
        resized = picture.resize((max(_CLIP_SIZE, round(width * scale)), max(_CLIP_SIZE, round(height * scale))),
                                 Image.Resampling.BICUBIC)
        left = (resized.width - _CLIP_SIZE) // 2
        top = (resized.height - _CLIP_SIZE) // 2
        cropped = resized.crop((left, top, left + _CLIP_SIZE, top + _CLIP_SIZE))
        pixels = (np.asarray(cropped, dtype=np.float32) / 255.0 - np.array(_CLIP_MEAN, dtype=np.float32)) \
            / np.array(_CLIP_STD, dtype=np.float32)
        feeds = _feeds(self.vision_session, {"pixel_values": pixels.transpose(2, 0, 1)[None, ...]})
        outputs = self.vision_session.run(None, feeds)
        return _unit_rows(self._named(self.vision_session, outputs, "image_embeds"))[0]


#: ``LocalModelSpec.runner`` -> the class that runs it.
RUNNERS: dict[str, Callable[[LocalModelSpec, Path], Any]] = {
    "bert_cls": BertClsEmbedder,
    "clip": ClipZeroShot,
}


def load_runner(spec: LocalModelSpec, folder: Path) -> Any:
    return RUNNERS[spec.runner](spec, folder)
