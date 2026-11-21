"""D2.01 S1: the reviewed-file table a chat's attachments are held to, and the limits it publishes."""
import pytest

from agent_runtime.conversations.prompt import (
    FILE_MEDIA_TYPES, MAX_FILE_BYTES, MAX_FILE_COUNT, MAX_FILES_TOTAL_BYTES, files_capability, media_type_allowed)


@pytest.mark.parametrize("media_type", ["image/png", "text/*", "application/octet-stream",
                                        "TEXT/PLAIN", "text/plain; charset=utf-8", "text"])
def test_media_types_outside_the_table_are_unsupported(media_type):
    assert not media_type_allowed(media_type)


@pytest.mark.parametrize("media_type", ["text/markdown", "application/json", "application/pdf"])
def test_media_types_in_the_table_are_accepted(media_type):
    assert media_type_allowed(media_type)


def test_the_published_limits_are_the_launcher_composers():
    assert files_capability() == {
        "max_count": MAX_FILE_COUNT, "max_file_bytes": MAX_FILE_BYTES,
        "max_total_bytes": MAX_FILES_TOTAL_BYTES, "media_types": list(FILE_MEDIA_TYPES)}
    assert (MAX_FILE_COUNT, MAX_FILE_BYTES, MAX_FILES_TOTAL_BYTES) == (8, 256 * 1024, 512 * 1024)
