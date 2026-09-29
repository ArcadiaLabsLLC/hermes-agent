"""``runtime.speech.*`` and ``runtime.admission.*`` — the bundled speech service and the one
model-memory admission authority (embedded-hermes D3 items 1-2).

Engines are fakes (the CI venv has neither faster-whisper nor Piper) EXCEPT in the
unavailable tests, which run the real ``SpeechEngines`` with the network and every
subprocess blocked: a missing or partial model must be answered before any loader or
downloader runs. Every check names its killing mutation; the reds are recorded in the
commit that added this file.
"""

from __future__ import annotations

import base64
import json
import socket
import struct
import subprocess
import threading
import time

import pytest

from agent_runtime import model_admission, speech_phonemize, speech_service
from agent_runtime.model_admission import AdmissionRefused, ModelAdmission
from agent_runtime.model_admission_client import BundledAdmissionClient
from agent_runtime.serve_rpc import RpcContext, handle_request

MiB = 1 << 20


# ── fixtures ────────────────────────────────────────────────────────────────


def _whisper_dir(root, *, drop=()):
    folder = root / "faster-whisper-tiny.en"
    folder.mkdir()
    for name, body in (("model.bin", b"\0" * 64), ("config.json", b"{}"), ("tokenizer.json", b"{}"),
                       ("vocabulary.txt", b"a\n")):
        if name not in drop:
            (folder / name).write_bytes(body)
    return folder


def _phonemizer(root, family, drop=()):
    """The phonemizer artifact a voice family reads, beside the voice (its bytes are never parsed here)."""
    for name in speech_phonemize.PHONEMIZER_ARTIFACTS[family]:
        if name not in drop:
            (root / name).write_bytes(b"\2" * 8)


def _piper_voice(root, *, sidecar=True, empty_onnx=False, phonemizer=True, phonemizer_drop=()):
    onnx = root / "en_US-test-low.onnx"
    onnx.write_bytes(b"" if empty_onnx else b"\1" * 64)
    if sidecar:
        (root / "en_US-test-low.onnx.json").write_text(json.dumps(
            {"audio": {"sample_rate": 16000}, "phoneme_type": "espeak", "espeak": {"voice": "en-us"}}))
    if phonemizer:
        _phonemizer(root, "piper", phonemizer_drop)
    return onnx


def _kokoro(root, *, voices=True, phonemizer_drop=()):
    model = root / "kokoro-v1.0.onnx"
    model.write_bytes(b"\1" * 64)
    if voices:
        (root / "voices-v1.0.bin").write_bytes(b"\3" * 32)
    _phonemizer(root, "kokoro", phonemizer_drop)
    return model


class FakeEngines:
    """Records loads; transcribes to a word count; synthesizes a fixed tone."""

    def __init__(self):
        self.loads = []
        self.passes = []

    def stt_importable(self, engine="faster-whisper"):
        return True

    def tts_importable(self):
        return True

    def load_stt(self, path, *, device, compute_type):
        self.loads.append(("stt", str(path), device, compute_type))
        return object()

    def transcribe(self, model, pcm, *, final):
        self.passes.append((len(pcm), final))
        return f"{'final' if final else 'partial'} {len(pcm) // 2} samples"

    def load_tts(self, path):
        self.loads.append(("tts", str(path)))
        return object()

    def unload_tts(self):
        pass

    def synthesize(self, voice, text):
        yield 16000, struct.pack("<h", 1000) * 20000   # 40 000 bytes -> two 32 KiB chunks
        yield 16000, struct.pack("<h", -1000) * 100


@pytest.fixture
def authority():
    value = ModelAdmission({"ram": 1 << 40})
    model_admission.set_admission(value)
    yield value
    model_admission.set_admission(None)


@pytest.fixture
def fakes(authority, tmp_path):
    engines = FakeEngines()
    svc = speech_service.SpeechService(engines=engines, configured=lambda: (None, None))
    speech_service.set_service(svc)
    yield engines, tmp_path
    speech_service.set_service(None)


class Wire:
    """One connection: its pushed notifications, and a call helper through the real dispatcher."""

    def __init__(self, key="conn-a"):
        self.events = []
        self.context = RpcContext(connection_key=key, transport="socket", emit=self.events.append)
        self._ids = iter(range(1, 10**6))

    def call(self, method, params=None):
        return handle_request({"jsonrpc": "2.0", "id": next(self._ids), "method": method,
                               "params": params or {}}, self.context)

    def result(self, method, params=None):
        frame = self.call(method, params)
        assert "error" not in frame, frame
        return frame["result"]

    def named(self, suffix):
        return [e["params"] for e in self.events if e["method"].endswith(suffix)]


def _loaded(wire, root):
    whisper, voice = _whisper_dir(root), _piper_voice(root)
    result = wire.result("runtime.speech.load", {"models_dir": str(root), "stt_model": whisper.name,
                                                  "tts_voice": voice.stem})
    assert result["results"]["stt"]["state"] == "loaded" and result["results"]["tts"]["state"] == "loaded", result
    return result


def _wait(predicate, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ── missing / partial -> unavailable, no network ───────────────────────────


@pytest.fixture
def no_network(monkeypatch):
    """Every socket connect and every child process raises; attempts are counted."""
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(args[:1])
        raise OSError("network and subprocesses are blocked in this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    return attempts


@pytest.fixture
def real_engines(authority, monkeypatch):
    """The real engines with the loaders counted — they must never be reached for a bad model."""
    engines = speech_service.SpeechEngines()
    reached = []
    monkeypatch.setattr(engines, "stt_importable", lambda *a: True)
    monkeypatch.setattr(engines, "tts_importable", lambda: True)
    monkeypatch.setattr(engines, "load_stt", lambda *a, **k: reached.append("stt"))
    monkeypatch.setattr(engines, "load_tts", lambda *a, **k: reached.append("tts"))
    svc = speech_service.SpeechService(engines=engines, configured=lambda: (None, None))
    speech_service.set_service(svc)
    yield reached
    speech_service.set_service(None)


@pytest.mark.parametrize("case, expected", [
    ("missing", ("model_missing", "model_missing")),
    ("partial", ("model_partial", "model_partial")),
    ("empty_file", ("model_partial", "model_partial")),
])
def test_a_missing_or_partial_model_reads_unavailable_with_no_network(case, expected, tmp_path, no_network,
                                                                      real_engines):
    """Mutation: drop the ``missing`` early return in ``inspect_stt`` / ``inspect_tts`` -> the
    partial rows read ``available`` and the loader is reached."""
    if case == "partial":
        _whisper_dir(tmp_path, drop=("model.bin",))
        _piper_voice(tmp_path, sidecar=False)
    elif case == "empty_file":
        _whisper_dir(tmp_path)
        (tmp_path / "faster-whisper-tiny.en" / "tokenizer.json").write_bytes(b"")
        _piper_voice(tmp_path, empty_onnx=True)
    params = {"models_dir": str(tmp_path), "stt_model": "faster-whisper-tiny.en", "tts_voice": "en_US-test-low"}
    wire = Wire()
    status = wire.result("runtime.speech.status", params)
    loaded = wire.result("runtime.speech.load", params)["results"]
    assert (status["stt"]["state"], status["tts"]["state"]) == ("unavailable", "unavailable")
    assert (status["stt"]["reason"], status["tts"]["reason"]) == expected
    assert (loaded["stt"]["reason"], loaded["tts"]["reason"]) == expected
    if case == "partial":
        assert status["stt"]["missing"] == ["model.bin"] and status["tts"]["missing"] == ["en_US-test-low.onnx.json"]
    assert real_engines == [] and no_network == []
    assert model_admission.admission().status()["reservations"] == []


def test_the_positive_control_a_complete_model_does_reach_the_loader(tmp_path, no_network, real_engines):
    """Same bytes as the partial row with the file restored: the loader IS reached, so the
    negative rows above are about the check, not a fixture that never gets that far."""
    _whisper_dir(tmp_path)
    _piper_voice(tmp_path)
    Wire().result("runtime.speech.load", {"models_dir": str(tmp_path), "stt_model": "faster-whisper-tiny.en",
                                          "tts_voice": "en_US-test-low"})
    assert real_engines == ["stt", "tts"] and no_network == []


def test_a_model_named_but_not_a_local_path_is_never_resolved_against_a_hub(authority, no_network,
                                                                            real_engines):
    """``stt.local.model: base`` is a Hub name upstream would download. Mutation: resolve a bare
    name without ``models_dir`` as a relative path -> ``model_missing`` instead of the typed reason."""
    svc = speech_service.SpeechService(engines=speech_service.service().engines,
                                       configured=lambda: ("base", "en_US-lessac-medium"))
    speech_service.set_service(svc)
    status = Wire().result("runtime.speech.status")
    assert (status["stt"]["reason"], status["tts"]["reason"]) == ("model_not_local", "model_not_local")
    assert real_engines == [] and no_network == []


def test_the_piper_resolver_downloads_nothing_under_hf_hub_offline(tmp_path, monkeypatch, no_network):
    """The bundled profile's HF_HUB_OFFLINE now covers Piper's voice download (upstream seam).
    Mutation: delete the seam's two lines -> the resolver spawns ``piper.download_voices``."""
    from tools.tts_tool_local import _resolve_piper_voice_path

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with pytest.raises(RuntimeError, match="HF_HUB_OFFLINE"):
        _resolve_piper_voice_path("en_US-lessac-medium", tmp_path)
    assert no_network == []
    monkeypatch.delenv("HF_HUB_OFFLINE")  # positive control: without the switch it DOES try to fetch
    with pytest.raises(OSError, match="blocked"):
        _resolve_piper_voice_path("en_US-lessac-medium", tmp_path)
    assert len(no_network) == 1


# ── admission ───────────────────────────────────────────────────────────────


def test_over_budget_is_refused_and_never_over_admitted():
    """Mutation: fit check ``used + bytes <= capacity`` -> ``used <= capacity`` -> the second
    reservation is admitted and the pool holds 110 of 100."""
    authority = ModelAdmission({"ram": 100})
    authority.reserve("llm:a", kind="llm", resource="ram", bytes=60)
    with pytest.raises(AdmissionRefused) as refused:
        authority.reserve("speech:stt", kind="stt", resource="vram", bytes=50)  # vram -> the one shared pool
    assert refused.value.reason == "over_budget" and refused.value.details["reserved_bytes"] == 60
    assert authority.status()["pools"]["ram"]["reserved_bytes"] == 60


def test_an_idle_evictable_model_is_evicted_and_a_busy_one_is_not():
    """Mutation: drop ``r.idle`` from the victim filter -> the busy model is evicted."""
    authority = ModelAdmission({"ram": 100})
    evicted = []
    authority.reserve("speech:tts", kind="tts", resource="ram", bytes=60,
                      evict=lambda: evicted.append("speech:tts"))
    with pytest.raises(AdmissionRefused):  # not marked idle yet: in use
        authority.reserve("llm:a", kind="llm", resource="ram", bytes=50)
    assert evicted == []
    authority.mark("speech:tts", idle=True)
    authority.reserve("llm:a", kind="llm", resource="ram", bytes=50)
    assert evicted == ["speech:tts"]
    assert [r["holder"] for r in authority.status()["reservations"]] == ["llm:a"]


def test_a_failed_eviction_keeps_its_bytes_counted():
    """Mutation: delete the victim's row even when its evictor raised -> the LLM is admitted
    while the speech model is still resident."""
    authority = ModelAdmission({"ram": 100})

    def refuse():
        raise RuntimeError("in use")

    authority.reserve("speech:stt", kind="stt", resource="ram", bytes=60, evict=refuse)
    authority.mark("speech:stt", idle=True)
    with pytest.raises(AdmissionRefused):
        authority.reserve("llm:a", kind="llm", resource="ram", bytes=50)
    assert authority.status()["pools"]["ram"]["reserved_bytes"] == 60


def test_concurrent_reservations_never_exceed_the_pool():
    """Twenty threads race for a pool that holds ten. Mutation: take the fit check and the insert
    under separate lock acquisitions -> more than ten are admitted."""
    authority = ModelAdmission({"ram": 100})
    barrier, admitted = threading.Barrier(20), []

    def race(i):
        barrier.wait()
        try:
            authority.reserve(f"llm:{i}", kind="llm", resource="ram", bytes=10)
            admitted.append(i)
        except AdmissionRefused:
            pass

    threads = [threading.Thread(target=race, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(admitted) == 10 and authority.status()["pools"]["ram"]["reserved_bytes"] == 100


def test_a_remote_lease_lapses_unless_renewed():
    clock = {"now": 0.0}
    authority = ModelAdmission({"ram": 100}, clock=lambda: clock["now"])
    authority.reserve("remote:full", kind="llm", resource="ram", bytes=80, owner="remote", lease_seconds=10)
    clock["now"] = 9.0
    authority.reserve("remote:full", kind="llm", resource="ram", bytes=80, owner="remote", lease_seconds=10)
    clock["now"] = 18.0
    assert authority.holds("remote:full")
    clock["now"] = 19.5
    authority.reserve("llm:b", kind="llm", resource="ram", bytes=90)
    assert not authority.holds("remote:full")


def test_a_remote_holder_cannot_replace_a_local_reservation(authority):
    """A wire caller naming ``speech:stt`` gets its own ``remote:`` row. Mutation: drop the
    ``remote:`` prefix in ``runtime.admission.reserve`` -> the local row is overwritten."""
    authority.reserve("speech:stt", kind="stt", resource="ram", bytes=100)
    Wire().result("runtime.admission.reserve", {"holder": "speech:stt", "kind": "llm", "resource": "ram",
                                                "bytes": 5})
    holders = {r["holder"]: r for r in Wire().result("runtime.admission.status")["reservations"]}
    assert holders["speech:stt"]["bytes"] == 100 and holders["speech:stt"]["owner"] == "local"
    assert holders["remote:speech:stt"]["bytes"] == 5


def test_the_client_helper_admits_refuses_and_releases_over_the_method_lane():
    authority = ModelAdmission({"vram": 100, "ram": 50})
    model_admission.set_admission(authority)
    try:
        wire = Wire()
        client = BundledAdmissionClient(lambda method, params: wire.call(method, params))
        assert client.reserve("llm-a", bytes=70, resource="vram")["pool"] == "vram"
        with pytest.raises(AdmissionRefused) as refused:
            client.reserve("llm-b", bytes=40, resource="vram")
        assert refused.value.reason == "over_budget" and refused.value.details["capacity_bytes"] == 100
        with client.lease("llm-c", bytes=40, resource="ram", lease_seconds=60):
            assert authority.holds("remote:llm-c")
        assert not authority.holds("remote:llm-c")
        assert client.release("llm-a") is True
        assert authority.status()["pools"]["vram"]["reserved_bytes"] == 0
    finally:
        model_admission.set_admission(None)


def test_a_speech_load_is_admitted_through_the_same_authority(tmp_path):
    """Speech and LLM share one budget: with an LLM holding the pool, the voice load is refused
    and nothing is loaded. Mutation: skip ``reserve`` in ``_load_slot`` -> the voice loads."""
    authority = ModelAdmission({"ram": 200 * MiB})
    model_admission.set_admission(authority)
    engines = FakeEngines()
    speech_service.set_service(speech_service.SpeechService(engines=engines, configured=lambda: (None, None)))
    try:
        authority.reserve("llm:a", kind="llm", resource="ram", bytes=150 * MiB)
        voice = _piper_voice(tmp_path)
        result = Wire().result("runtime.speech.load", {"which": "tts", "tts_voice": str(voice)})
        assert result["results"]["tts"]["state"] == "refused"
        assert result["results"]["tts"]["reason"] == "over_budget"
        assert engines.loads == [] and result["tts"]["state"] == "available"
    finally:
        speech_service.set_service(None)
        model_admission.set_admission(None)


def test_an_idle_speech_model_is_evicted_for_an_llm_and_a_recognizing_one_is_not(tmp_path):
    authority = ModelAdmission({"ram": 400 * MiB})
    model_admission.set_admission(authority)
    speech_service.set_service(speech_service.SpeechService(engines=FakeEngines(), configured=lambda: (None, None)))
    try:
        wire = Wire()
        _loaded(wire, tmp_path)
        stream = wire.result("runtime.speech.recognize.begin")["stream_id"]
        with pytest.raises(AdmissionRefused):
            authority.reserve("llm:a", kind="llm", resource="ram", bytes=320 * MiB)
        wire.result("runtime.speech.recognize.cancel", {"stream_id": stream})
        authority.reserve("llm:a", kind="llm", resource="ram", bytes=320 * MiB)
        status = wire.result("runtime.speech.status")
        assert status["stt"]["unloaded_reason"] == "evicted"
        assert sum(r["bytes"] for r in status["admission"]["reservations"]) <= 400 * MiB
    finally:
        speech_service.set_service(None)
        model_admission.set_admission(None)


# ── RPC round trip ──────────────────────────────────────────────────────────


def _pcm(ms):
    return struct.pack("<h", 300) * (16 * ms)


def test_recognize_streams_partials_and_a_final_over_the_method_lane(fakes):
    """Mutation: drop the partial scheduling in ``recognize_push`` -> no partial event."""
    engines, root = fakes
    wire = Wire()
    _loaded(wire, root)
    begun = wire.result("runtime.speech.recognize.begin", {"sample_rate": 16000})
    sid = begun["stream_id"]
    assert begun["partials"] is True
    for seq in range(10):  # 1 s in 100 ms chunks
        ack = wire.result("runtime.speech.recognize.push", {"stream_id": sid, "seq": seq,
                                                            "audio": base64.b64encode(_pcm(100)).decode()})
        assert ack["seq"] == seq
    assert _wait(lambda: wire.named(".partial"))
    final = wire.result("runtime.speech.recognize.end", {"stream_id": sid})
    assert final["text"] == "final 16000 samples" or final["adopted_partial"]
    assert final["audio_ms"] == 1000
    assert _wait(lambda: wire.named(".final"))
    assert wire.named(".final")[0]["text"] == final["text"]
    assert wire.named(".partial")[0]["stream_id"] == sid
    assert wire.call("runtime.speech.recognize.push", {"stream_id": sid, "seq": 10, "audio": ""})["error"][
        "data"]["reason"] == "stream_not_found"


def test_a_stream_refuses_a_sequence_gap_another_connection_and_bad_audio(fakes):
    engines, root = fakes
    wire, other = Wire("conn-a"), Wire("conn-b")
    _loaded(wire, root)
    sid = wire.result("runtime.speech.recognize.begin")["stream_id"]
    chunk = base64.b64encode(_pcm(100)).decode()
    gap = wire.call("runtime.speech.recognize.push", {"stream_id": sid, "seq": 1, "audio": chunk})
    assert gap["error"]["data"] == {"reason": "seq_gap", "expected": 0}
    foreign = other.call("runtime.speech.recognize.push", {"stream_id": sid, "seq": 0, "audio": chunk})
    assert foreign["error"]["data"]["reason"] == "stream_not_found"
    odd = wire.call("runtime.speech.recognize.push", {"stream_id": sid, "seq": 0,
                                                      "audio": base64.b64encode(b"\0\0\0").decode()})
    assert odd["error"]["data"]["reason"] == "audio_invalid"
    rate = wire.call("runtime.speech.recognize.begin", {"sample_rate": 44100})
    assert rate["error"]["data"]["reason"] == "audio_format_unsupported"


def test_synthesize_pushes_base64_pcm_chunks_then_replies(fakes):
    engines, root = fakes
    wire = Wire()
    _loaded(wire, root)
    reply = wire.result("runtime.speech.synthesize", {"text": "Hello there."})
    chunks = wire.named(".synthesize.chunk")
    audio = b"".join(base64.b64decode(c["audio"]) for c in chunks)
    assert [c["seq"] for c in chunks] == list(range(reply["chunks"])) == [0, 1, 2]
    assert len(audio) == reply["bytes"] == 40200
    assert max(len(base64.b64decode(c["audio"])) for c in chunks) <= speech_service.OUT_CHUNK_BYTES
    assert reply["sample_rate"] == 16000 and reply["encoding"] == "pcm_s16le"
    no_channel = handle_request({"jsonrpc": "2.0", "id": 9, "method": "runtime.speech.synthesize",
                                 "params": {"text": "x"}}, RpcContext())
    assert no_channel["error"]["data"]["reason"] == "push_channel_required"


def test_recognize_and_synthesize_refuse_before_a_model_is_loaded(fakes):
    wire = Wire()
    assert wire.call("runtime.speech.recognize.begin")["error"]["data"]["reason"] == "model_not_loaded"
    assert wire.call("runtime.speech.synthesize", {"text": "x"})["error"]["data"]["reason"] == "model_not_loaded"


def test_unload_releases_the_reservations(fakes, authority):
    engines, root = fakes
    wire = Wire()
    _loaded(wire, root)
    assert {r["holder"] for r in authority.status()["reservations"]} == {"speech:stt", "speech:tts"}
    wire.result("runtime.speech.unload")
    assert authority.status()["reservations"] == []


def test_unloading_speech_to_text_ends_its_open_streams(fakes):
    """Mutation: ``_unload_slot`` stops clearing ``_streams`` -> the stream still answers after STT unload."""
    engines, root = fakes
    wire = Wire()
    _loaded(wire, root)
    sid = wire.result("runtime.speech.recognize.begin")["stream_id"]
    chunk = base64.b64encode(_pcm(100)).decode()
    wire.result("runtime.speech.unload", {"which": "tts"})
    # Positive control: unloading the OTHER model leaves the stream open.
    assert wire.result("runtime.speech.recognize.push", {"stream_id": sid, "seq": 0, "audio": chunk})["seq"] == 0
    wire.result("runtime.speech.unload", {"which": "stt"})
    gone = wire.call("runtime.speech.recognize.push", {"stream_id": sid, "seq": 1, "audio": chunk})
    assert gone["error"]["data"]["reason"] == "stream_not_found"


# ── the phonemizer artifact (no espeak-ng) ─────────────────────────────────


@pytest.mark.parametrize("drop", [("openphonemizer-en_us.onnx",), ("openphonemizer-en_us.json",)])
def test_a_voice_without_its_phonemizer_reads_unavailable_before_the_loader(drop, tmp_path, no_network,
                                                                            real_engines):
    """No phonemizer, no speech: typed before the loader, never a load that fails or says nothing.
    Mutation: drop the ``phonemizer_missing`` return in ``inspect_tts`` -> the voice reads available
    and the loader is reached. Positive control:
    ``test_the_positive_control_a_complete_model_does_reach_the_loader`` (the same voice, artifact whole)."""
    _piper_voice(tmp_path, phonemizer_drop=drop)
    params = {"models_dir": str(tmp_path), "tts_voice": "en_US-test-low", "which": "tts"}
    wire = Wire()
    status = wire.result("runtime.speech.status", params)["tts"]
    loaded = wire.result("runtime.speech.load", params)["results"]["tts"]
    expected = ("unavailable", "phonemizer_missing", list(drop), "piper")
    assert (status["state"], status["reason"], status["missing"], status["voice_family"]) == expected
    assert (loaded["state"], loaded["reason"], loaded["missing"], loaded["voice_family"]) == expected
    assert real_engines == [] and no_network == []


def test_kokoro_is_a_voice_with_its_voices_file_and_its_own_phonemizer(tmp_path, no_network, real_engines):
    """Kokoro has no ``.onnx.json``: its companion is ``voices-v1.0.bin`` and its phonemizer misaki's.
    Mutation: keep the ``.onnx.json`` companion for every voice -> Kokoro reads ``model_partial``."""
    folder = tmp_path / "kokoro"
    folder.mkdir()
    model = _kokoro(folder)
    status = Wire().result("runtime.speech.status", {"tts_voice": str(model)})["tts"]
    assert (status["state"], status["voice_family"], status["sample_rate"]) == ("available", "kokoro", 24000)
    Wire().result("runtime.speech.load", {"which": "tts", "tts_voice": str(model)})
    assert real_engines == ["tts"]
    Wire().result("runtime.speech.unload", {"which": "tts"})
    # A Piper artifact beside Kokoro is not Kokoro's: misaki's is what it needs.
    for name in speech_phonemize.PHONEMIZER_ARTIFACTS["kokoro"]:
        (folder / name).unlink()
    _phonemizer(folder, "piper")
    status = Wire().result("runtime.speech.status", {"tts_voice": str(model)})["tts"]
    assert (status["reason"], status["missing"]) == ("phonemizer_missing", list(
        speech_phonemize.PHONEMIZER_ARTIFACTS["kokoro"]))
    (folder / "voices-v1.0.bin").write_bytes(b"")
    status = Wire().result("runtime.speech.status", {"tts_voice": str(model)})["tts"]
    assert (status["reason"], status["missing"]) == ("model_partial", ["voices-v1.0.bin"])
    assert no_network == []


def test_the_bundled_tts_engine_is_onnxruntime_never_piper_tts(monkeypatch):
    """The pack ships no ``piper`` package: availability asks for onnxruntime + numpy only.
    Mutation: route ``tts_importable`` back through ``piper_engine_importable`` -> red here."""
    import importlib.util

    real = importlib.util.find_spec
    asked = []

    def spec(name, *args):
        asked.append(name)
        return object() if name in ("onnxruntime", "numpy") else None

    monkeypatch.setattr(importlib.util, "find_spec", spec)
    assert speech_service.SpeechEngines().tts_importable() is True
    assert "piper" not in asked
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "onnxruntime" else real(name))
    assert speech_service.SpeechEngines().tts_importable() is False


# ── PyAV is not in the speech pack ──────────────────────────────────────────


def test_loading_whisper_registers_the_av_placeholder_first(tmp_path, monkeypatch):
    """Mutation: drop ``ensure_av_placeholder()`` from ``SpeechEngines.load_stt`` -> the loader
    sees no ``av`` and (for real) ``import faster_whisper`` raises ModuleNotFoundError."""
    import sys

    from agent_runtime import _upstream_doors, speech_decode

    monkeypatch.setitem(sys.modules, "av", None)  # PyAV not installed
    seen = []
    monkeypatch.setattr(_upstream_doors, "whisper_load_model",
                        lambda *a, **k: seen.append(speech_decode.is_av_placeholder(sys.modules.get("av"))))
    speech_service.SpeechEngines().load_stt(_whisper_dir(tmp_path), device="cpu", compute_type="int8")
    assert seen == [True]


# ── Parakeet TDT: the engine the model folder's files name ──────────────────


PARAKEET_SET = ("config.json", "vocab.txt", "encoder-model.int8.onnx", "decoder_joint-model.int8.onnx")


def _parakeet_dir(root, *, drop=()):
    folder = root / "parakeet-tdt-0.6b-v2-int8"
    folder.mkdir()
    for name in PARAKEET_SET:
        if name not in drop:
            body = b'{"model_type": "nemo-conformer-tdt", "features_size": 128}' if name == "config.json" else b"\3" * 64
            (folder / name).write_bytes(body)
    return folder


def test_the_model_folders_files_choose_the_engine_and_its_reservation(fakes, authority):
    """Mutation: ``engine_for`` always answers faster-whisper -> the Parakeet folder reads
    ``model_partial`` (no ``model.bin``); Parakeet's estimate swapped for whisper's -> the
    reservation is 160 MiB short."""
    engines, root = fakes
    parakeet, whisper = _parakeet_dir(root), _whisper_dir(root)
    wire = Wire()
    status = wire.result("runtime.speech.status", {"stt_model": str(parakeet)})["stt"]
    assert (status["state"], status["engine"]) == ("available", "parakeet-tdt")
    loaded = wire.result("runtime.speech.load", {"which": "stt", "stt_model": str(parakeet)})
    disk = sum(f.stat().st_size for f in parakeet.iterdir())
    assert loaded["results"]["stt"]["reserved_bytes"] == disk + 256 * MiB
    assert loaded["stt"]["engine"] == "parakeet-tdt"
    # Positive control: the whisper folder, through the same service, reads the other engine.
    swapped = wire.result("runtime.speech.load", {"which": "stt", "stt_model": str(whisper)})
    assert swapped["stt"]["engine"] == "faster-whisper"
    assert swapped["results"]["stt"]["reserved_bytes"] == sum(f.stat().st_size for f in whisper.iterdir()) + 96 * MiB


@pytest.mark.parametrize("drop", ["encoder-model.int8.onnx", "config.json"])
def test_a_partial_parakeet_folder_reads_unavailable_with_no_network(drop, tmp_path, no_network, real_engines):
    """A torn Parakeet download is judged against Parakeet's list, before any loader. Mutation:
    drop ``encoder-model*.onnx`` from ``engine_for``'s markers -> the config-less folder is judged
    as whisper (``missing`` names ``model.bin``). The positive control is the complete folder."""
    _parakeet_dir(tmp_path, drop=(drop,))
    params = {"models_dir": str(tmp_path), "stt_model": "parakeet-tdt-0.6b-v2-int8", "which": "stt"}
    status = Wire().result("runtime.speech.status", params)["stt"]
    loaded = Wire().result("runtime.speech.load", params)["results"]["stt"]
    assert (status["reason"], status["engine"], status["missing"]) == ("model_partial", "parakeet-tdt", [drop])
    assert loaded["reason"] == "model_partial"
    assert real_engines == [] and no_network == []
    (tmp_path / "parakeet-tdt-0.6b-v2-int8" / drop).write_bytes(
        b'{"model_type": "nemo-conformer-tdt"}' if drop == "config.json" else b"\3")
    Wire().result("runtime.speech.load", params)
    assert real_engines == ["stt"] and no_network == []


def test_parakeet_loads_by_model_type_from_the_local_folder_on_cpu(tmp_path, monkeypatch):
    """onnx-asr stood in: the real ``SpeechEngines`` hands it the model TYPE (never a Hub name,
    which its resolver would download) and the folder, int8, CPU. Mutation: pass
    ``nemo-parakeet-tdt-0.6b-v2`` -> red."""
    import sys
    import types

    calls, heard = [], []

    class Model:
        def recognize(self, audio, sample_rate):
            heard.append((len(audio), sample_rate))
            return " hello "

    def load_model(model, path, **kwargs):
        calls.append((model, path, kwargs))
        return Model()

    monkeypatch.setitem(sys.modules, "onnx_asr", types.SimpleNamespace(load_model=load_model))
    folder = _parakeet_dir(tmp_path)
    engines = speech_service.SpeechEngines()
    model = engines.load_stt(folder, device="cpu", compute_type="int8")
    assert calls == [("nemo-conformer-tdt", str(folder),
                      {"quantization": "int8", "providers": ["CPUExecutionProvider"]})]
    pytest.importorskip("numpy")  # the speech pack's; the CI test venv has none
    assert engines.transcribe(model, _pcm(500), final=False) == "hello"
    assert heard == [(8000, 16000)]


def _speech_with_gaps(seconds):
    """Loud 16 kHz samples with a 300 ms silence every 1.3 s: an inter-word gap to cut in."""
    import numpy as np

    # Never periodic: two chunks with equal bytes would share one cache entry.
    samples = (8000 + np.arange(seconds * 16000) // 16000).astype(np.int16)
    for start in range(10400, len(samples), 20800):
        samples[start:start + 4800] = 0
    return samples


def test_parakeet_decodes_a_growing_take_chunk_by_chunk_and_each_chunk_once():
    """Mutation: ``chunk_cuts`` returns no cut -> one 35 s pass (the memory the chunking
    bounds); skip the cache lookup in ``_chunk_text`` -> the second pass re-decodes the
    finished chunks (the second pass decodes four chunks, not two)."""
    pytest.importorskip("numpy")  # the speech pack's; the CI test venv has none
    from agent_runtime.speech_stt_engines import CHUNK_SECONDS, ParakeetRunner, chunk_cuts

    lengths = []

    class Model:
        def recognize(self, audio, sample_rate):
            lengths.append(len(audio))
            return f"w{len(lengths)}"

    samples = _speech_with_gaps(35)
    runner = ParakeetRunner(Model())
    runner.transcribe(samples[:30 * 16000].tobytes())
    first_pass = list(lengths)
    assert len(first_pass) >= 3 and max(first_pass) < CHUNK_SECONDS * 16000
    cuts = chunk_cuts(samples)
    assert cuts[:len(first_pass) - 1] == chunk_cuts(samples[:30 * 16000])  # cuts never move
    assert all(samples[cut] == 0 for cut in cuts)  # every cut lands in a gap
    lengths.clear()
    text = runner.transcribe(samples.tobytes())
    # Only the chunk the new audio closed and the open tail; the finished chunks come from cache.
    assert lengths == [cuts[-1] - cuts[-2], len(samples) - cuts[-1]]
    assert text.split()[:len(first_pass) - 1] == [f"w{i}" for i in range(1, len(first_pass))]
