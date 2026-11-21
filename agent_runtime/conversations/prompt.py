"""The reviewed-file limits a chat's attachments are held to; one table for server and Launcher.

The prompt packet these limits once validated rode ``runtime.conversation.send``, retired with the
profile-scoped conversation path (RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT). The operator
chat's files (``operator_files``) are held to the same table and publish it in the serve manifest.
"""
from __future__ import annotations

import re

__layer__ = "lanes"

#: Reviewed-file limits. The aggregate is the launcher composer's own bound
#: (``EterniaLauncher/packages/agents/eternia_agent_client/lib/src/conversation/
#: agent_attachment.dart`` ``AgentAttachmentLimits``: count 8, 256 KiB per file,
#: 512 KiB total), so server and UI agree (owner ruling D2.01, 2026-10-10).
MAX_FILE_COUNT = 8
MAX_FILE_BYTES = 256 * 1024
MAX_FILES_TOTAL_BYTES = 512 * 1024
#: ``text/*`` admits every text subtype; the rest are exact.
FILE_MEDIA_TYPES = ("text/*", "application/json", "application/xml", "application/yaml",
                    "text/csv", "application/pdf")
_MEDIA_TOKEN = re.compile(r"[a-z0-9][a-z0-9.+-]*")


def files_capability() -> dict:
    return {"max_count": MAX_FILE_COUNT, "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_FILES_TOTAL_BYTES, "media_types": list(FILE_MEDIA_TYPES)}


def media_type_allowed(media_type: str) -> bool:
    kind, _, subtype = media_type.partition("/")
    if not (_MEDIA_TOKEN.fullmatch(kind) and _MEDIA_TOKEN.fullmatch(subtype)):
        return False
    return media_type in FILE_MEDIA_TYPES or f"{kind}/*" in FILE_MEDIA_TYPES
