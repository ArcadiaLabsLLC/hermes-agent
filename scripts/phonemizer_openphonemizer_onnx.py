"""Export OpenPhonemizer's checkpoint to the speech pack's phonemizer artifact (no torch at runtime).

Fork-owned (bundled desktop, GPL-free speech pack; launcher
``docs/embedded_hermes/planned/GPL_FREE_TTS_OPTIONS_2026-09-28.md``). A dev-machine
step, never run by bundled Hermes: it needs ``torch`` and ``deep-phonemizer``
(both BSD/MIT), which the speech pack does not ship.

Input: ``openphonemizer/ckpt`` ``best_model.pt`` (BSD-3-Clause-Clear) — a
DeepPhonemizer forward transformer plus its word dictionary. Output, two files
the Launcher downloads next to a Piper voice:

    openphonemizer-en_us.onnx   the transformer, logits over phoneme tokens
    openphonemizer-en_us.json   tokenizers, char_repeats, and the word dictionary

``agent_runtime/speech_phonemize.py`` (``OpenPhonemizer``) runs them on
onnxruntime. ``--check N`` compares the ONNX model with the torch one over N
dictionary words (argmax tokens must agree) and prints the result.

    python scripts/phonemizer_openphonemizer_onnx.py --checkpoint best_model.pt --out <dir> [--quantize] [--check 2000]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ARTIFACT = "openphonemizer-en_us"
FORMAT = 1


def _load(checkpoint: Path):
    import torch
    from dp.model.model import ForwardTransformer

    data = torch.load(checkpoint, map_location="cpu", weights_only=False)
    model = ForwardTransformer.from_config(data["config"])
    model.load_state_dict(data["model"])
    model.eval()
    return model, data


def _sidecar(data: dict) -> dict:
    pre = data["preprocessor"]
    text, phon = pre.text_tokenizer, pre.phoneme_tokenizer
    return {
        "format": FORMAT,
        "source": "openphonemizer/ckpt best_model.pt (BSD-3-Clause-Clear)",
        "language": "en_us",
        "char_repeats": text.char_repeats,
        "lowercase": bool(text.lowercase),
        "text_tokens": text.token_to_idx,
        "phoneme_tokens": {str(i): t for i, t in phon.idx_to_token.items()},
        "start_index": text._get_start_index("en_us"),
        "end_index": phon.end_index,
        "dictionary": data["phoneme_dict"]["en_us"],
    }


class _Logits:
    """``ForwardTransformer.forward`` over a bare ``[1, T]`` token tensor (no padding at batch 1)."""

    def __new__(cls, model):
        import torch

        class Wrapped(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.inner = model

            def forward(self, text):
                x = text.transpose(0, 1)
                x = self.inner.embedding(x)
                x = self.inner.pos_encoder(x)
                x = self.inner.encoder(x)
                return self.inner.fc_out(x).transpose(0, 1)

        return Wrapped().eval()


def export(checkpoint: Path, out: Path, *, quantize: bool) -> dict:
    import torch

    model, data = _load(checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    onnx_path = out / f"{ARTIFACT}.onnx"
    sample = torch.tensor([[1] + [3] * 12 + [2]], dtype=torch.int64)
    time = torch.export.Dim("time", min=3, max=4000)
    program = torch.onnx.export(_Logits(model), (sample,), input_names=["text"], output_names=["logits"],
                                dynamic_shapes=({1: time},), opset_version=18, dynamo=True)
    program.save(str(onnx_path))
    if quantize:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        fp32 = onnx_path.with_suffix(".fp32.onnx")
        onnx_path.replace(fp32)
        quantize_dynamic(str(fp32), str(onnx_path), weight_type=QuantType.QInt8)
        fp32.unlink()
    sidecar = out / f"{ARTIFACT}.json"
    sidecar.write_text(json.dumps(_sidecar(data), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (onnx_path, sidecar)}


def check(checkpoint: Path, out: Path, count: int) -> dict:
    """Argmax agreement between torch and the exported model on ``count`` dictionary words."""
    import numpy as np
    import onnxruntime as ort
    import torch

    model, data = _load(checkpoint)
    wrapped = _Logits(model)
    session = ort.InferenceSession(str(out / f"{ARTIFACT}.onnx"), providers=["CPUExecutionProvider"])
    tokenizer = data["preprocessor"].text_tokenizer
    words = random.Random(7).sample(sorted(data["phoneme_dict"]["en_us"]), count)
    same = 0
    for word in words:
        ids = tokenizer(word, "en_us")
        with torch.no_grad():
            expected = wrapped(torch.tensor([ids])).argmax(-1).numpy()
        got = session.run(None, {"text": np.array([ids], dtype=np.int64)})[0].argmax(-1)
        same += int(np.array_equal(expected, got))
    return {"words": count, "identical_argmax": same}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--quantize", action="store_true", help="dynamic int8 weights")
    parser.add_argument("--check", type=int, default=0, metavar="N")
    args = parser.parse_args(argv)
    report = {"files": export(args.checkpoint, args.out, quantize=args.quantize)}
    if args.check:
        report["check"] = check(args.checkpoint, args.out, args.check)
    json.dump(report, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
