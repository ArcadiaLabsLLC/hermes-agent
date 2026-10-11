"""D2.01 S1: the reviewed-file arm of the native prompt packet and its capability."""
import base64
import hashlib

import pytest

from agent_runtime.conversations import binding
from agent_runtime.conversations.model import ConversationError, Refusal
from agent_runtime.conversations.prompt import (
    FILE_MEDIA_TYPES, MAX_FILE_BYTES, MAX_FILE_COUNT, MAX_FILES_TOTAL_BYTES, MAX_PROMPT_BYTES,
    validate)


def _file(payload: bytes, name="notes.txt", media_type="text/plain") -> dict:
    return {"name": name, "media_type": media_type, "data": base64.b64encode(payload).decode()}


def _refused(prompt) -> Refusal:
    with pytest.raises(ConversationError) as caught:
        validate(prompt)
    return caught.value.reason


def test_old_shape_prompt_stays_valid_with_no_files():
    assert validate({"text": "hi", "images": []}) == []


def test_files_answer_server_computed_identity():
    payload = b"alpha,beta\n1,2\n"
    identity = validate({"text": "", "images": [], "files": [_file(payload, "t.csv", "text/csv")]})
    assert identity == [{"name": "t.csv", "media_type": "text/csv", "size_bytes": len(payload),
                         "sha256": hashlib.sha256(payload).hexdigest()}]


def test_unknown_prompt_or_file_keys_are_invalid_requests():
    assert _refused({"text": "", "images": [], "files": [], "paths": []}) is Refusal.INVALID_REQUEST
    extra = {**_file(b"x"), "sha256": "client-claim"}
    assert _refused({"text": "", "images": [], "files": [extra]}) is Refusal.INVALID_REQUEST
    assert _refused({"text": "", "images": [], "files": {}}) is Refusal.INVALID_REQUEST


def test_per_file_bound_is_exact():
    assert validate({"text": "", "images": [], "files": [_file(b"a" * MAX_FILE_BYTES)]})
    over = {"text": "", "images": [], "files": [_file(b"a" * (MAX_FILE_BYTES + 1))]}
    assert _refused(over) is Refusal.FILE_OVERSIZE


def test_aggregate_and_count_bounds():
    share = MAX_FILES_TOTAL_BYTES // 2
    at_bound = [_file(b"a" * share, f"{n}.txt") for n in range(2)]
    assert len(validate({"text": "", "images": [], "files": at_bound})) == 2
    over = at_bound + [_file(b"a", "extra.txt")]
    assert _refused({"text": "", "images": [], "files": over}) is Refusal.FILE_OVERSIZE
    many = [_file(b"a", f"{n}.txt") for n in range(MAX_FILE_COUNT + 1)]
    assert _refused({"text": "", "images": [], "files": many}) is Refusal.FILE_OVERSIZE


def test_files_are_not_counted_against_the_serialized_prompt_bound():
    text = "t" * (MAX_PROMPT_BYTES - 64)
    big = _file(b"a" * MAX_FILE_BYTES)
    assert validate({"text": text, "images": [], "files": [big, _file(b"b", "b.txt")]})


@pytest.mark.parametrize("media_type", ["image/png", "text/*", "application/octet-stream",
                                        "TEXT/PLAIN", "text/plain; charset=utf-8", "text"])
def test_media_types_outside_the_table_are_unsupported(media_type):
    prompt = {"text": "", "images": [], "files": [_file(b"x", media_type=media_type)]}
    assert _refused(prompt) is Refusal.FILE_UNSUPPORTED


@pytest.mark.parametrize("media_type", ["text/markdown", "application/json", "application/pdf"])
def test_media_types_in_the_table_are_accepted(media_type):
    assert validate({"text": "", "images": [], "files": [_file(b"x", media_type=media_type)]})


@pytest.mark.parametrize("file", [
    {"name": "a.txt", "media_type": "text/plain", "data": "not base64!"},
    {"name": "a.txt", "media_type": "text/plain", "data": ""},
    _file(b"x", name="../etc/passwd"),
    _file(b"x", name="C:\\a.txt"),
    _file(b"x", name=""),
])
def test_invalid_file_content_or_name_is_file_invalid(file):
    assert _refused({"text": "", "images": [], "files": [file]}) is Refusal.FILE_INVALID


def test_capability_v3_publishes_the_file_limits(tmp_path):
    service = binding.bind(tmp_path, "install")
    try:
        capabilities = service.capabilities()
    finally:
        binding.shutdown(root=tmp_path)
    assert capabilities["version"] == 3
    assert capabilities["files"] == {
        "max_count": MAX_FILE_COUNT, "max_file_bytes": MAX_FILE_BYTES,
        "max_total_bytes": MAX_FILES_TOTAL_BYTES, "media_types": list(FILE_MEDIA_TYPES)}
    assert (MAX_FILE_COUNT, MAX_FILE_BYTES, MAX_FILES_TOTAL_BYTES) == (8, 256 * 1024, 512 * 1024)
