"""Measure a built bundle against the D4 release ceilings; print JSON for the Launcher's release lane.

Fork-owned (bundled desktop, plan D4). Measures, never judges: the ceilings
(installer delta, ready time, dictation latency) and the verdict belong to the
Launcher's release lane, which reads this script's JSON.

* ``size`` — installed bytes and the LZMA2 preset-9 (xz, the codec 7z and
  Inno Setup use) size of a deterministic tar of the core's ``app/`` and
  ``site-packages/`` (and, with ``--interpreter-dir``, of the interpreter plus
  the core), and of each ``--pack``.
* ``ready`` — seconds from process start to serve's ``{"event":"ready"}``
  frame, running ``hermes_cli.main harness serve --ndjson`` from the bundle
  under ``--python -I -S`` (bundle site-packages + app on the path, as the
  installer's layout puts them) with an empty ``HERMES_HOME``. ``cold`` is the
  first start of the bundle as built (bytecode baked by
  ``bundle_profile_package.py --bake-with`` when it was; the OS file cache is
  not flushed); ``warm`` are the following starts against the same home.
* ``stt`` — with the speech pack on the path and an STT model directory in the
  Launcher's layout (``--stt-model``: a Whisper or Parakeet ONNX folder, as
  ``agent_runtime.speech_stt_engines.engine_for`` reads it): model load
  seconds, then ``first_words_s`` — a partial transcription of the first
  ``--first-chunk`` seconds of ``--stt-audio`` through the speech service's own
  ``SpeechEngines.transcribe`` — and ``final_s``, the final transcription of
  the whole clip. ``null`` with a reason when there is no model or no pack.

Usage::

    python scripts/bundle_ceilings.py --core <core dir> --python <target python> \\
        [--pack <speech pack dir>] [--interpreter-dir <dir>] [--stt-model <dir>] [--json out.json]
"""

from __future__ import annotations

import argparse
import io
import json
import lzma
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIO = ROOT / "tools" / "neutts_samples" / "jo.wav"
MIB = 1024 * 1024


# -- size -------------------------------------------------------------------------------------------


class _Counter(io.RawIOBase):
    def __init__(self) -> None:
        self.compressor = lzma.LZMACompressor(format=lzma.FORMAT_XZ, preset=9)
        self.compressed = 0

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        self.compressed += len(self.compressor.compress(bytes(data)))
        return len(data)

    def finish(self) -> int:
        self.compressed += len(self.compressor.flush())
        return self.compressed


def _files(roots: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    out = []
    for prefix, root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                out.append((f"{prefix}/{path.relative_to(root).as_posix()}", path))
    return out


def lzma_size(roots: list[tuple[str, Path]]) -> dict:
    """Installed bytes and xz preset-9 bytes of a deterministic tar of ``roots``."""
    counter = _Counter()
    installed = 0
    with tarfile.open(fileobj=counter, mode="w|", format=tarfile.PAX_FORMAT) as tar:
        for arcname, path in _files(roots):
            info = tarfile.TarInfo(arcname)
            info.size = path.stat().st_size
            info.mtime, info.mode = 0, 0o644
            installed += info.size
            with path.open("rb") as handle:
                tar.addfile(info, handle)
    compressed = counter.finish()
    return {"installed_bytes": installed, "lzma_bytes": compressed,
            "installed_mib": round(installed / MIB, 2), "lzma_mib": round(compressed / MIB, 2)}


# -- time to ready ------------------------------------------------------------------------------------

_SERVE_DRIVER = r"""
import runpy, site, sys
site_dir, app_dir = sys.argv[1:3]
site.addsitedir(site_dir)
sys.path.append(app_dir)
sys.argv = ["hermes", "harness", "serve", "--ndjson"]
runpy.run_module("hermes_cli.main", run_name="__main__", alter_sys=True)
"""


def _bundle_env(home: Path, packs: list[Path]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "HERMES"))}
    env["HERMES_HOME"] = str(home)
    env["HERMES_ENGINE_PACKS"] = os.pathsep.join(str(p / "site-packages") for p in packs)
    return env


def time_to_ready(python: Path, core: Path, home: Path, packs: list[Path], timeout: float = 120.0,
                  log: Path | None = None) -> float | None:
    """Seconds from spawn to the ``ready`` frame, or None (with ``log`` holding stderr)."""
    stderr = log.open("ab") if log else subprocess.DEVNULL
    try:
        start = time.perf_counter()
        proc = subprocess.Popen([str(python), "-I", "-S", "-c", _SERVE_DRIVER, str(core / "site-packages"),
                                 str(core / "app")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=stderr, env=_bundle_env(home, packs), cwd=str(home))
        found: list[float] = []
        seen = threading.Event()

        def read() -> None:
            for raw in proc.stdout:
                try:
                    frame = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(frame, dict) and frame.get("event") == "ready":
                    found.append(time.perf_counter() - start)
                    seen.set()
                    return

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            seen.wait(timeout)
            ready = found[0] if found else None
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=15)
        return ready
    finally:
        if log:
            stderr.close()


# -- dictation latency -------------------------------------------------------------------------------

_STT_DRIVER = r"""
import json, site, sys, time, wave
from pathlib import Path
site_dir, app_dir, model_dir, audio, first_chunk = sys.argv[1:6]
site.addsitedir(site_dir)
sys.path.append(app_dir)
import numpy as np
from agent_runtime.speech_service import SpeechEngines
with wave.open(audio) as w:
    rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
    raw = w.readframes(w.getnframes())
samples = np.frombuffer(raw, dtype={1: np.uint8, 2: np.int16, 4: np.int32}[width]).astype(np.float32)
samples = samples.reshape(-1, channels).mean(axis=1) / float(2 ** (8 * width - 1))
if rate != 16000:  # linear resample to the 16 kHz mono PCM the Launcher sends
    n = int(round(len(samples) * 16000 / rate))
    samples = np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples)
pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
engines = SpeechEngines()
t = time.perf_counter(); model = engines.load_stt(Path(model_dir), device="cpu", compute_type="int8")
load_s = time.perf_counter() - t
first = pcm[: int(float(first_chunk) * 16000)].tobytes()
t = time.perf_counter(); partial = engines.transcribe(model, first, final=False)
first_words_s = time.perf_counter() - t
t = time.perf_counter(); final = engines.transcribe(model, pcm.tobytes(), final=True)
final_s = time.perf_counter() - t
print(json.dumps({"load_s": round(load_s, 3), "first_words_s": round(first_words_s, 3),
                  "final_s": round(final_s, 3), "audio_s": round(len(pcm) / 16000, 2),
                  "first_chunk_s": float(first_chunk), "partial_text": partial, "final_text": final}))
"""


def stt_latency(python: Path, core: Path, packs: list[Path], model: Path | None, audio: Path,
                first_chunk: float, home: Path) -> dict:
    if model is None:
        return {"measured": False, "reason": "model_not_present",
                "detail": "pass --stt-model <a Whisper or Parakeet ONNX folder, the Launcher's layout>"}
    if not packs:
        return {"measured": False, "reason": "no_speech_pack", "detail": "pass --pack <speech pack dir>"}
    done = subprocess.run([str(python), "-I", "-S", "-c", _STT_DRIVER, str(core / "site-packages"),
                           str(core / "app"), str(model), str(audio), str(first_chunk)],
                          capture_output=True, text=True, timeout=600, env=_bundle_env(home, packs),
                          cwd=str(home))
    if done.returncode != 0:
        return {"measured": False, "reason": "stt_run_failed",
                "detail": (done.stderr.strip().splitlines() or ["(no output)"])[-1]}
    return {"measured": True, "model": str(model), **json.loads(done.stdout.strip().splitlines()[-1])}


# -- main ---------------------------------------------------------------------------------------------


def measure(core: Path, python: Path, packs: list[Path], interpreter_dir: Path | None, warm_runs: int,
            model: Path | None, audio: Path, first_chunk: float, log: Path | None) -> dict:
    record = json.loads((core / "bundle-manifest.json").read_text(encoding="utf-8"))
    size = {"core": lzma_size([("app", core / "app"), ("site-packages", core / "site-packages")])}
    if interpreter_dir:
        size["core_with_interpreter"] = lzma_size([("python", interpreter_dir), ("app", core / "app"),
                                                   ("site-packages", core / "site-packages")])
    for pack in packs:
        size[f"pack:{json.loads((pack / 'engine-pack.json').read_text(encoding='utf-8'))['pack']}"] = \
            lzma_size([("site-packages", pack / "site-packages")])
    with tempfile.TemporaryDirectory(prefix="hermes-ceilings-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cold = time_to_ready(python, core, home, [], log=log)
        warm = [time_to_ready(python, core, home, [], log=log) for _ in range(warm_runs)]
        stt = stt_latency(python, core, packs, model, audio, first_chunk, home)
    ok = [w for w in warm if w is not None]
    return {
        "schema": 1, "profile": record["profile"], "target": record["target"], "commit": record["commit"],
        "baked": (core / ".hermes-baked-pycache").is_file(),
        "python": str(python), "python_version": subprocess.run(
            [str(python), "-c", "import sys; print(sys.version.split()[0])"], capture_output=True, text=True,
            timeout=60).stdout.strip(),
        "size": size,
        "ready": {"cold_s": None if cold is None else round(cold, 3),
                  "warm_s": [None if w is None else round(w, 3) for w in warm],
                  "warm_median_s": round(sorted(ok)[len(ok) // 2], 3) if ok else None},
        "stt": stt,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True, help="the target interpreter")
    parser.add_argument("--pack", type=Path, action="append", default=[])
    parser.add_argument("--interpreter-dir", type=Path, help="installed interpreter to include in the size")
    parser.add_argument("--warm-runs", type=int, default=2)
    parser.add_argument("--stt-model", type=Path)
    parser.add_argument("--stt-audio", type=Path, default=DEFAULT_AUDIO)
    parser.add_argument("--first-chunk", type=float, default=2.0, help="seconds of audio in the first partial")
    parser.add_argument("--serve-log", type=Path, help="append the serve runs' stderr here")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    result = measure(args.core, args.python, args.pack, args.interpreter_dir, args.warm_runs,
                     args.stt_model, args.stt_audio, args.first_chunk, args.serve_log)
    text = json.dumps(result, indent=2)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["ready"]["cold_s"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
