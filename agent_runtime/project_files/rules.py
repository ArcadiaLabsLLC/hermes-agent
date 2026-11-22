"""The rule spec's values, as hermes' reader uses them.

Eternia's ``packages/eternia_file_tree_spec/spec/rules.json`` is the one owner; the
vendored mirror's copy is pinned to these constants by
``tests/agent_runtime/test_project_files_rules_pin.py``.
"""

from __future__ import annotations

__layer__ = "models"

MAX_PATH_LENGTH = 2048
NEVER_LISTED = (".git",)
SKIP_DIRECTORIES = (".dart_tool", ".gradle", ".pytest_cache", ".venv", "__pycache__", "build",
                    "node_modules")
MAX_READ_BYTES = 5 * 1024 * 1024
BINARY_PROBE_BYTES = 8192
DEFAULT_DEPTH = 2
MAX_DEPTH = 6
MAX_ENTRIES = 200
READ_PAGE_CODE_POINTS = 20000
MIN_PATTERN = 1
MAX_PATTERN = 256
MAX_MATCHES = 200
LINE_CODE_POINTS = 240
MAX_GLOB = 256
MAX_WILDCARDS = 16
SEARCH_DEADLINE_MS = 2000
WRITE_OPS = ("write", "patch", "move", "delete")

REFUSAL_CODES = (
    "invalid_path", "outside_root", "not_found", "ignored", "not_a_file", "not_a_directory",
    "too_large", "binary", "not_text", "bad_argument", "grant_revoked", "virtual_root_read_only",
    "virtual_tree_unavailable", "not_a_git_root", "search_timeout",
)


class ProjectFileRefusal(Exception):
    """A refused request: its spec ``code`` and a sentence for the caller."""

    def __init__(self, code: str, message: str) -> None:
        if code not in REFUSAL_CODES:
            raise ValueError(f"not a spec refusal code: {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
