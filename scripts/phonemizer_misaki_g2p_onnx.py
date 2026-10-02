"""Export misaki's English G2P (lexicon + neural fallback) to the speech pack's Kokoro phonemizer artifact.

Fork-owned (bundled desktop, GPL-free speech pack; launcher
``docs/embedded_hermes/planned/GPL_FREE_TTS_OPTIONS_2026-09-28.md``). A dev-machine
step, never run by bundled Hermes: it needs ``torch``, ``transformers`` and a
misaki checkout, none of which the speech pack ships.

Inputs (all Apache-2.0): misaki's ``us_gold.json`` / ``us_silver.json`` lexicons
and ``PeterReid/graphemes_to_phonemes_en_us`` (the BART model misaki's
``FallbackNetwork`` runs for a word its lexicon lacks). Output, two files the
Launcher downloads next to Kokoro's model:

    misaki-en_us-g2p.onnx   the BART model, one full forward per decode step
    misaki-en_us-g2p.json   grapheme/phoneme tables, special ids, both lexicons, and
                            Kokoro v1.0's phoneme->token vocabulary (hexgrad/Kokoro-82M
                            ``config.json``, Apache-2.0) — the model these phonemes feed

``agent_runtime/speech_phonemize.py`` (``MisakiG2P``) runs them on onnxruntime.
``--check N`` greedy-decodes N lexicon words with torch (``generate``) and with
the ONNX model and counts identical outputs.

    python scripts/phonemizer_misaki_g2p_onnx.py --misaki-data <misaki/data dir> --kokoro-config <config.json> --out <dir> [--check 500]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ARTIFACT = "misaki-en_us-g2p"
MODEL = "PeterReid/graphemes_to_phonemes_en_us"
FORMAT = 1
MAX_STEPS = 64


def _load_g2p_model():
    from transformers import BartForConditionalGeneration

    model = BartForConditionalGeneration.from_pretrained(MODEL)
    model.eval()
    return model


def _sidecar(model, data_dir: Path, kokoro_config: Path) -> dict:
    config = model.config
    return {
        "format": FORMAT,
        "source": f"{MODEL} (Apache-2.0); misaki us_gold/us_silver (Apache-2.0)",
        "graphemes": config.grapheme_chars,
        "phonemes": config.phoneme_chars,
        "start_id": config.decoder_start_token_id,
        "bos_id": config.bos_token_id,
        "eos_id": config.eos_token_id,
        "unknown_id": 3,
        "max_steps": min(MAX_STEPS, config.max_position_embeddings),
        "gold": json.loads((data_dir / "us_gold.json").read_text(encoding="utf-8")),
        "silver": json.loads((data_dir / "us_silver.json").read_text(encoding="utf-8")),
        "kokoro_vocab": json.loads(kokoro_config.read_text(encoding="utf-8"))["vocab"],
    }


def _wrapped(model):
    import torch

    class Logits(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.inner = model

        def forward(self, input_ids, decoder_input_ids):
            return self.inner(input_ids=input_ids, decoder_input_ids=decoder_input_ids).logits

    return Logits().eval()


def export(data_dir: Path, kokoro_config: Path, out: Path) -> dict:
    import torch

    model = _load_g2p_model()
    out.mkdir(parents=True, exist_ok=True)
    onnx_path = out / f"{ARTIFACT}.onnx"
    enc = torch.export.Dim("enc", min=2, max=MAX_STEPS)
    dec = torch.export.Dim("dec", min=1, max=MAX_STEPS)
    sample = (torch.tensor([[1, 5, 6, 7, 2]]), torch.tensor([[1, 5]]))
    program = torch.onnx.export(_wrapped(model), sample, input_names=["input_ids", "decoder_input_ids"],
                                output_names=["logits"], dynamic_shapes=({1: enc}, {1: dec}),
                                opset_version=18, dynamo=True)
    program.save(str(onnx_path))
    sidecar = out / f"{ARTIFACT}.json"
    sidecar.write_text(json.dumps(_sidecar(model, data_dir, kokoro_config), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (onnx_path, sidecar)}


def check(out: Path, count: int) -> dict:
    """Identical greedy output from ``generate`` (torch) and the ONNX loop on ``count`` words."""
    import numpy as np
    import onnxruntime as ort
    import torch

    model = _load_g2p_model()
    meta = json.loads((out / f"{ARTIFACT}.json").read_text(encoding="utf-8"))
    session = ort.InferenceSession(str(out / f"{ARTIFACT}.onnx"), providers=["CPUExecutionProvider"])
    index = {g: i for i, g in enumerate(meta["graphemes"])}
    words = random.Random(7).sample(sorted(w for w in meta["gold"] if w.isalpha()), count)
    same = 0
    for word in words:
        ids = [meta["bos_id"]] + [index.get(c, meta["unknown_id"]) for c in word] + [meta["eos_id"]]
        with torch.no_grad():
            expected = model.generate(input_ids=torch.tensor([ids]), max_length=meta["max_steps"])[0].tolist()
        got = [meta["start_id"]]
        for _ in range(meta["max_steps"] - 1):
            logits = session.run(None, {"input_ids": np.array([ids], dtype=np.int64),
                                        "decoder_input_ids": np.array([got], dtype=np.int64)})[0]
            got.append(int(logits[0, -1].argmax()))
            if got[-1] == meta["eos_id"]:
                break
        same += int(got == expected)
    return {"words": count, "identical": same}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--misaki-data", type=Path, required=True, help="misaki/data (us_gold.json, us_silver.json)")
    parser.add_argument("--kokoro-config", type=Path, required=True, help="hexgrad/Kokoro-82M config.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check", type=int, default=0, metavar="N")
    args = parser.parse_args(argv)
    report = {"files": export(args.misaki_data, args.kokoro_config, args.out)}
    if args.check:
        report["check"] = check(args.out, args.check)
    json.dump(report, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
