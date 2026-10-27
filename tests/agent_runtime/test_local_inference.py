"""``runtime.embed.texts`` / ``runtime.vision.tag`` (RT-LOCAL-EMBED-TEXTS, RT-LOCAL-IMAGE-TAG).

Runners are fakes behind ``LocalInferenceService(loader=…)``: the test venv has neither numpy nor
onnxruntime, and no test loads a real model or touches the network (a real-model check is the live
row ``RT-LOCAL-INFERENCE-LIVE``). The tokenizers are the real pure-Python ones over tiny vocabularies.
Each check names its killing mutation; the reds are recorded in the commit that added this file.
"""

from __future__ import annotations

import base64
import io
import math

import pytest
from PIL import Image

from agent_runtime.local_inference import service as inference
from agent_runtime.local_inference.clip_bpe import ClipBpe
from agent_runtime.local_inference.models import EMBED_MODELS, VISION_MODELS
from agent_runtime.local_inference.wordpiece import WordPiece
from agent_runtime.model_admission import ModelAdmission
from agent_runtime.serve_rpc import handle_request

BGE, CLIP = "bge-small-en-v1.5", "clip-vit-base-patch32"
_ROOMY = 1 << 40


def _authority(ram=_ROOMY):
    return ModelAdmission({"ram": ram})


def _unit(dim, hot):
    row = [0.0] * dim
    for index, weight in hot.items():
        row[index] = weight
    norm = math.sqrt(sum(v * v for v in row))
    return [v / norm for v in row]


class _FakeEmbedder:
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [_unit(384, {i: 1.0, 383: 0.5}) for i, _ in enumerate(texts)]


class _FakeClip:
    """Label ``i`` points at axis ``i``; the image leans on axis 1, then axis 0."""

    def __init__(self):
        self.text_calls, self.image_calls = [], 0

    def text_embeds(self, prompts):
        self.text_calls.append(list(prompts))
        return [_unit(512, {i: 1.0}) for i, _ in enumerate(prompts)]

    def image_embeds(self, image):
        self.image_calls += 1
        return _unit(512, {0: 0.3, 1: 0.6, 2: 0.1})


@pytest.fixture
def models_dir(tmp_path):
    for spec in (*EMBED_MODELS.values(), *VISION_MODELS.values()):
        folder = tmp_path / spec.model
        folder.mkdir()
        for name in spec.files:
            (folder / name).write_bytes(b"\4" * 16)
    return tmp_path


@pytest.fixture
def runners(monkeypatch):
    made = {"bert_cls": _FakeEmbedder(), "clip": _FakeClip()}
    loads = []

    def loader(spec, folder):
        loads.append((spec.model, folder.name))
        return made[spec.runner]

    inference.set_service(inference.LocalInferenceService(loader=loader, absent_modules=lambda: [],
                                                          authority=_authority()))
    yield made, loads
    inference.set_service(None)


def _call(method, params):
    return handle_request({"jsonrpc": "2.0", "id": 3, "method": method, "params": params})


def _png(size=(32, 20)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 10, 10)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


# ── runtime.embed.texts ─────────────────────────────────────────────────────


def test_vectors_are_little_endian_float32_per_text(models_dir, runners):
    # Kill: ``encode_vector`` packs ``>`` (big-endian) -> the decoded rows differ, red.
    frame = _call("runtime.embed.texts", {"model": BGE, "models_dir": str(models_dir), "texts": ["a", "b"]})
    result = frame["result"]
    assert (result["contract"], result["model"], result["dim"], result["encoding"]) == (1, BGE, 384, "f32le_base64")
    rows = [inference.decode_vector(v) for v in result["vectors"]]
    expected = [_unit(384, {0: 1.0, 383: 0.5}), _unit(384, {1: 1.0, 383: 0.5})]
    assert all(len(base64.b64decode(v)) == 384 * 4 for v in result["vectors"])
    assert all(math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-7) for got, want in zip(rows, expected)
               for a, b in zip(got, want))


def test_a_partial_folder_is_named_before_any_load(models_dir, runners):
    # Kill: drop the ``missing`` check in ``model_folder`` -> the fake loads and answers, red.
    _made, loads = runners
    (models_dir / BGE / "vocab.txt").unlink()
    frame = _call("runtime.embed.texts", {"model": BGE, "models_dir": str(models_dir), "texts": ["a"]})
    assert frame["error"]["code"] == 4001
    assert frame["error"]["data"]["reason"] == "model_partial" and frame["error"]["data"]["missing"] == ["vocab.txt"]
    assert loads == []
    # Positive control: the complete folder loads.
    (models_dir / BGE / "vocab.txt").write_bytes(b"x")
    assert "result" in _call("runtime.embed.texts", {"model": BGE, "models_dir": str(models_dir), "texts": ["a"]})
    assert loads == [(BGE, BGE)]


def test_no_speech_pack_is_engine_missing(models_dir):
    # Kill: drop the ``absent`` check in ``_load`` -> the loader runs, red.
    loads = []
    inference.set_service(inference.LocalInferenceService(
        loader=lambda spec, folder: loads.append(spec) or _FakeEmbedder(), absent_modules=lambda: ["onnxruntime"]))
    try:
        frame = _call("runtime.embed.texts", {"model": BGE, "models_dir": str(models_dir), "texts": ["a"]})
    finally:
        inference.set_service(None)
    assert frame["error"]["data"] == {"reason": "engine_missing", "modules": ["onnxruntime"]} and loads == []


@pytest.mark.parametrize("params, reason", [
    ({"model": "bge-large", "texts": ["a"]}, "model_unknown"),
    ({"model": BGE, "models_dir": "relative/dir", "texts": ["a"]}, "models_dir_invalid"),
    ({"model": BGE, "texts": []}, "texts_empty"),
    ({"model": BGE, "texts": ["a"] * 65}, "texts_too_many"),
    ({"model": BGE, "texts": [3]}, "text_invalid"),
])
def test_bad_embed_params_are_refused(models_dir, runners, params, reason):
    # Kill: drop the ``MAX_TEXTS`` check -> the 65-text case answers, red.
    params = {"models_dir": str(models_dir), **params}
    frame = _call("runtime.embed.texts", params)
    assert frame["error"]["code"] == -32602 and frame["error"]["data"]["reason"] == reason


def test_a_runner_of_the_wrong_width_fails_loud(models_dir, runners):
    # Kill: drop the width check in ``_checked_rows`` -> a 3-wide vector rides the wire, red.
    made, _loads = runners
    made["bert_cls"].embed = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]
    frame = _call("runtime.embed.texts", {"model": BGE, "models_dir": str(models_dir), "texts": ["a"]})
    assert frame["error"]["data"]["reason"] == "handler_failed"


def test_loaded_runners_are_bounded(models_dir, tmp_path):
    # Kill: drop the ``MAX_LOADED`` trim -> three runners stay loaded, red.
    authority = _authority()
    service = inference.LocalInferenceService(loader=lambda spec, folder: _FakeEmbedder(), absent_modules=lambda: [],
                                              authority=authority)
    for index in range(3):
        other = tmp_path / f"m{index}"
        (other / BGE).mkdir(parents=True)
        for name in EMBED_MODELS[BGE].files:
            (other / BGE / name).write_bytes(b"x")
        service.embed_texts({"model": BGE, "models_dir": str(other), "texts": ["a"]})
    assert len(service._loaded) == inference.MAX_LOADED
    # Kill: ``_trim`` stops releasing -> three reservations outlive two runners, red.
    assert len(authority.status()["reservations"]) == inference.MAX_LOADED


# ── admission (RT-LOCAL-INFERENCE-ADMISSION) ────────────────────────────────


def _service(authority, loader=None):
    return inference.LocalInferenceService(loader=loader or (lambda spec, folder: _FakeEmbedder()),
                                           absent_modules=lambda: [], authority=authority)


def _embed(service, models_dir):
    return service.embed_texts({"model": BGE, "models_dir": str(models_dir), "texts": ["a"]})


def test_a_load_reserves_its_estimate_under_its_kind_and_goes_idle(models_dir):
    # Kill: drop the ``reserve`` in ``_load`` -> no reservation is listed, red.
    authority = _authority()
    _embed(_service(authority), models_dir)
    (row,) = authority.status()["reservations"]
    disk = sum((models_dir / BGE / name).stat().st_size for name in EMBED_MODELS[BGE].files)
    assert row["holder"].startswith(inference.HOLDER_PREFIX + BGE + ":")
    assert (row["kind"], row["pool"], row["evictable"], row["idle"]) == ("embed", "ram", True, True)
    assert row["bytes"] == int(disk * inference._DISK_FACTOR) + inference._SESSION_OVERHEAD


def test_the_vision_model_reserves_as_vision(models_dir):
    authority = _authority()
    clip = _FakeClip()
    service = _service(authority, loader=lambda spec, folder: clip)
    service.tag_image({"model": CLIP, "models_dir": str(models_dir), "image": _png(), "labels": ["cat", "dog"]})
    assert [r["kind"] for r in authority.status()["reservations"]] == ["vision"]


def test_a_load_over_budget_is_refused_before_the_loader_runs(models_dir):
    # Kill: drop the ``reserve`` in ``_load`` -> the fake loads and answers, red.
    loads = []
    inference.set_service(_service(_authority(ram=1024), loader=lambda spec, folder: loads.append(spec) or _FakeEmbedder()))
    try:
        frame = _call("runtime.embed.texts", {"model": BGE, "models_dir": str(models_dir), "texts": ["a"]})
    finally:
        inference.set_service(None)
    assert frame["error"]["code"] == 4090 and frame["error"]["data"]["reason"] == "over_budget"
    assert loads == []
    # Positive control: the same call with room answers.
    inference.set_service(_service(_authority()))
    try:
        assert "result" in _call("runtime.embed.texts", {"model": BGE, "models_dir": str(models_dir), "texts": ["a"]})
    finally:
        inference.set_service(None)


def test_an_idle_runner_is_evicted_to_admit_another_model(models_dir):
    # Kill: reserve without ``evict`` -> the speech reservation is refused over_budget, red.
    estimate = inference._estimate_bytes(EMBED_MODELS[BGE], models_dir / BGE)
    authority = _authority(ram=estimate + 10)
    service = _service(authority)
    _embed(service, models_dir)
    authority.reserve("speech:stt", kind="stt", resource="ram", bytes=estimate)
    assert service._loaded == {} and [r["holder"] for r in authority.status()["reservations"]] == ["speech:stt"]


def test_a_runner_in_use_refuses_eviction(models_dir):
    # Kill: ``_use`` stops marking the holder busy -> the mid-call reservation evicts it, red.
    # Kill: drop the ``users`` check in ``_evict`` -> the direct mid-call evict succeeds, red.
    estimate = inference._estimate_bytes(EMBED_MODELS[BGE], models_dir / BGE)
    authority = _authority(ram=estimate + 10)
    seen, armed = [], []

    class _Reserving(_FakeEmbedder):
        def embed(self, texts):
            if not armed:  # the first call loads; the second finds the runner idle, then holds it
                return super().embed(texts)
            seen.append(authority.status()["reservations"][0]["idle"])
            try:
                authority.reserve("speech:stt", kind="stt", resource="ram", bytes=estimate)
                seen.append("admitted")
            except Exception as refusal:  # AdmissionRefused
                seen.append(getattr(refusal, "reason", type(refusal).__name__))
            try:
                service._evict((BGE, str(models_dir / BGE)))
                seen.append("evicted")
            except RuntimeError:
                seen.append("in_use")
            return super().embed(texts)

    service = _service(authority, loader=lambda spec, folder: _Reserving())
    _embed(service, models_dir)
    assert authority.status()["reservations"][0]["idle"] is True
    armed.append(True)
    _embed(service, models_dir)
    assert seen == [False, "over_budget", "in_use"] and len(service._loaded) == 1


def test_a_failed_load_releases_its_reservation(models_dir):
    # Kill: drop the ``release`` on the load-failure branch -> the reservation outlives the failure, red.
    authority = _authority()

    def broken(spec, folder):
        raise OSError("bad onnx")

    with pytest.raises(inference.LocalInferenceRefused) as refused:
        _embed(_service(authority, loader=broken), models_dir)
    assert refused.value.reason == "load_failed" and authority.status()["reservations"] == []


# ── runtime.vision.tag ──────────────────────────────────────────────────────


def _tag(models_dir, **extra):
    params = {"model": CLIP, "models_dir": str(models_dir), "image": _png(), "labels": ["cat", "dog", "car"], **extra}
    return _call("runtime.vision.tag", params)


def test_scores_are_the_top_k_softmax_over_the_vocabulary(models_dir, runners):
    # Kill: sort ``ranked`` ascending -> "dog" is not first, red.
    frame = _tag(models_dir, top_k=2)
    result = frame["result"]
    assert result["contract"] == 1 and result["model"] == CLIP
    assert [entry["label"] for entry in result["scores"]] == ["dog", "cat"]
    logits = [100 * x for x in _unit(512, {0: 0.3, 1: 0.6, 2: 0.1})[:3]]
    total = sum(math.exp(v - max(logits)) for v in logits)
    assert math.isclose(result["scores"][0]["score"], math.exp(logits[1] - max(logits)) / total, abs_tol=1e-6)
    made, _ = runners
    assert made["clip"].text_calls == [["a photo of cat.", "a photo of dog.", "a photo of car."]]


def test_label_embeddings_are_cached_per_vocabulary(models_dir, runners):
    # Kill: skip the ``_vocabularies`` lookup in ``_label_rows`` -> the repeat embeds the labels again, red.
    made, _ = runners
    _tag(models_dir)
    _tag(models_dir)
    assert len(made["clip"].text_calls) == 1 and made["clip"].image_calls == 2
    # Positive control: another vocabulary (order counts) is embedded.
    _tag(models_dir, labels=["dog", "cat", "car"])
    assert len(made["clip"].text_calls) == 2


def test_an_image_over_two_mib_is_refused_before_decoding(models_dir, runners):
    # Kill: drop the decoded-length check -> the oversized PNG reaches the runner, red.
    made, _ = runners
    big = base64.b64encode(b"\x89PNG" + b"\0" * (inference.MAX_IMAGE_BYTES)).decode()
    frame = _tag(models_dir, image=big)
    assert frame["error"]["data"]["reason"] == "image_too_large" and made["clip"].image_calls == 0


@pytest.mark.parametrize("extra, reason", [
    ({"image": base64.b64encode(b"not a picture").decode()}, "image_unreadable"),
    ({"image": "%%%"}, "image_invalid"),
    ({"labels": ["cat", "cat"]}, "labels_duplicate"),
    ({"labels": []}, "labels_empty"),
    ({"labels": ["a\nb"]}, "label_invalid"),
    ({"labels": ["x" * 65]}, "label_too_long"),
    ({"top_k": 4}, "top_k_invalid"),
    ({"model": "siglip"}, "model_unknown"),
])
def test_bad_tag_params_are_refused(models_dir, runners, extra, reason):
    # Kill: drop the ``_check_decodable`` call -> the non-picture reaches the runner, red.
    frame = _tag(models_dir, **extra)
    assert frame["error"]["code"] == -32602 and frame["error"]["data"]["reason"] == reason
    made, _ = runners
    assert made["clip"].image_calls == 0


# ── tokenizers (pure Python) ────────────────────────────────────────────────


def test_wordpiece_splits_like_bert():
    # Kill: drop the ``##`` prefix in ``_pieces`` -> "unaffable" is [UNK], red.
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "un", "##aff", "##able", "hello", ",", "world", "!", "cafe"]
    tokenizer = WordPiece({token: i for i, token in enumerate(vocab)}, max_tokens=8)
    assert tokenizer.encode("Hello, unaffable WORLD! Café zzz") == [2, 7, 8, 4, 5, 6, 9, 3]
    # Truncation keeps [CLS] … [SEP] at max_tokens; positive control: a short text is not cut.
    assert tokenizer.encode("hello") == [2, 7, 3]


def test_clip_bpe_merges_by_rank_and_closes_words():
    # Kill: drop ``</w>`` from the last symbol in ``_bpe`` -> "cat</w>" is never formed, red.
    vocab = {"<|startoftext|>": 100, "<|endoftext|>": 101, "c": 1, "a": 2, "t</w>": 3, "ca": 4, "cat</w>": 5,
             ".</w>": 6, "a</w>": 7}
    tokenizer = ClipBpe(vocab, [("c", "a"), ("ca", "t</w>")])
    assert tokenizer.encode("A  CAT.") == [100, 7, 5, 6, 101]
    # Positive control: without the second merge the word stays split.
    assert ClipBpe(vocab, [("c", "a")]).encode("cat") == [100, 4, 3, 101]
