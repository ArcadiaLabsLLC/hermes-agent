"""Reviewed files on the operator chat send (RT-MISSION-CHAT-MESSAGE-TAKES).

Fork module ``agent_runtime/operator_files.py``: the native lane's ``prompt.files`` item shape and
limits on ``runtime.chat.message``, stored content-addressed with a name sidecar, named on argv by
reference, and staged for the agent as ``FILE:<path>`` lines (plan
``docs/agent-runtime-harness/archive/p10-turn-2026-10-19.md`` §3.5).
"""

from __future__ import annotations

import base64

import pytest

from agent_runtime import operator_files as of
from agent_runtime.conversations import prompt


def _file(data=b"hello\n", media_type="text/plain", name="notes.txt"):
    return {"name": name, "media_type": media_type, "data": base64.b64encode(data).decode("ascii")}


@pytest.fixture
def store(tmp_path):
    return tmp_path / "store"


KIB = 1024


# Plan test 1. Killing mutation: compare per-file size only (drop the running total) -> the
# aggregate case (two 200 KiB files) is admitted.
@pytest.mark.parametrize(("files", "reason"), [
    ([_file()] * (prompt.MAX_FILE_COUNT + 1), of.REASON_FILE_OVERSIZE),             # nine files
    ([_file(b"x" * (300 * KIB))], of.REASON_FILE_OVERSIZE),                         # one 300 KiB file
    # The aggregate: each file under 256 KiB, together 550 KiB > 512 KiB. (The plan's "two 200 KiB
    # files" is 400 KiB, under the bound; the tree's numbers win.)
    ([_file(b"x" * (200 * KIB)), _file(b"y" * (200 * KIB)), _file(b"w" * (150 * KIB))], of.REASON_FILE_OVERSIZE),
    ([_file(media_type="image/png")], of.REASON_FILE_UNSUPPORTED),
    ([{"name": "a.txt", "media_type": "text/plain", "data": "!!notb64!!"}], of.REASON_FILE_INVALID),
    ([_file(name="dir/a.txt")], of.REASON_FILE_INVALID),
    ([{"name": "a.txt", "media_type": "text/plain"}], of.REASON_FILE_INVALID),     # missing data
    ("not-a-list", of.REASON_FILE_INVALID),
])
def test_invalid_files_are_refused_with_the_native_spellings(files, reason):
    with pytest.raises(of.OperatorFilesInvalid) as caught:
        of.normalize_files(files)
    assert caught.value.reason == reason


def test_two_files_under_every_bound_are_admitted_and_the_spellings_are_the_native_refusals():
    parts = of.normalize_files([_file(b"x" * (200 * KIB)), _file(b"{}", "application/json", "a.json")])
    assert [p.media_type for p in parts] == ["text/plain", "application/json"]
    from agent_runtime.conversations.model import Refusal

    assert {of.REASON_FILE_INVALID, of.REASON_FILE_OVERSIZE, of.REASON_FILE_UNSUPPORTED} == {
        Refusal.FILE_INVALID, Refusal.FILE_OVERSIZE, Refusal.FILE_UNSUPPORTED}
    assert of.files_limits() == prompt.files_capability()


# Plan test 2. Killing mutation: drop the sidecar write -> resolve_refs cannot name the file.
def test_store_files_is_content_addressed_and_writes_the_name_sidecar(store):
    first = of.normalize_files([_file(b"same bytes\n", name="first.txt")])
    second = of.normalize_files([_file(b"same bytes\n", name="second.txt")])
    refs = of.store_files(first, store_root=store) + of.store_files(second, store_root=store)
    assert refs[0] == refs[1] and refs[0].endswith(".txt")
    stored = {p.name for p in (store / of.FILES_DIRNAME).iterdir()}
    assert stored == {refs[0].removeprefix("sha256:"), f"{first[0].sha256}{of.SIDECAR_SUFFIX}"}
    [resolved] = of.resolve_refs(refs[:1], store_root=store)
    assert (resolved.name, resolved.media_type, resolved.size_bytes) == ("first.txt", "text/plain", 11)
    assert resolved.path.read_bytes() == b"same bytes\n"


def test_media_types_store_under_their_canonical_extension(store):
    parts = of.normalize_files([_file(b"%PDF-1.4", "application/pdf", "a.pdf"), _file(b"# h", "text/markdown", "a.md"),
                                _file(b"x", "text/x-python", "a.py")])
    assert [ref.rsplit(".", 1)[1] for ref in of.store_files(parts, store_root=store)] == ["pdf", "md", "txt"]


# Plan test 3. Killing mutation: return [] for a reference that names nothing -> a silent drop.
@pytest.mark.parametrize("ref", ["sha256:" + "a" * 64 + ".txt", "sha256:" + "a" * 64 + ".exe", "../etc/passwd"])
def test_resolve_refs_refuses_an_unknown_reference_file_invalid(store, ref):
    with pytest.raises(of.OperatorFilesInvalid) as caught:
        of.resolve_refs([ref], store_root=store)
    assert caught.value.reason == of.REASON_FILE_INVALID


def test_with_file_lines_stages_one_path_line_per_file_and_one_guidance_sentence(store):
    refs = of.store_files(of.normalize_files([_file(name="a.txt"), _file(b"{}", "application/json", "b.json")]),
                          store_root=store)
    resolved = of.resolve_refs(refs, store_root=store)
    text = of.with_file_lines("look at these", resolved)
    lines = text.splitlines()
    assert lines[0] == "look at these"
    assert lines[2] == of.FILE_GUIDANCE.format(names="a.txt, b.json")
    assert lines[3:] == [f"FILE:{item.path}" for item in resolved]
    assert of.with_file_lines("plain", []) == "plain"


def test_a_file_line_joins_the_media_scope_only_inside_the_operator_file_store(isolate_agent_runtime_root):
    """``media_handles`` learns the ``FILE:`` prefix (one table, two rows). Killing mutation: admit
    every ``FILE:`` payload (drop the containment) -> the out-of-store line parses."""

    from agent_runtime import media_handles

    [ref] = of.store_files(of.normalize_files([_file(b"scope me\n")]))
    [resolved] = of.resolve_refs([ref])
    line = f"FILE:{resolved.path}"
    assert media_handles.parse_media_declaration(line) == str(resolved.path)
    outside = resolved.path.parent.parent / resolved.path.name
    assert media_handles.parse_media_declaration(f"FILE:{outside}") is None
    assert media_handles.parse_media_declaration(f"MEDIA:{resolved.path}") is None  # images only on MEDIA:
    assert media_handles.media_declarations(f"hi\n{line}\nMEDIA:/x/a.png") == [str(resolved.path), "/x/a.png"]
    artifact = media_handles._artifact_for(str(resolved.path))
    assert (artifact.media_type, artifact.size_bytes) == ("text/plain", 9)
