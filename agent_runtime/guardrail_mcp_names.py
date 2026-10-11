"""The filesystem MCP read tools, spelled as the registry spells them, in the guardrail's idempotent set.

Upstream ``agent/tool_guardrails.py::IDEMPOTENT_TOOL_NAMES`` lists the filesystem MCP
read tools with the retired single-underscore prefix (``mcp_filesystem_read_file``),
while the registry names them ``mcp__filesystem__read_file``
(``tools/mcp_tool_schema.py::mcp_prefixed_tool_name``, #33533). The guard compares the
raw registered name, so its no-progress check never saw those tools as idempotent.

``ToolCallGuardrailConfig.idempotent_tools`` defaults through a lambda that reads the
module global at construction time, so rebinding the global (old names kept) is the whole
fix; the eternia-harness plugin calls :func:`add_registry_spelled_filesystem_reads` at
register. Retires when upstream derives the names itself (upstream PR draft D4).
"""

from __future__ import annotations

__layer__ = "policy"

#: The filesystem server's read-only tools upstream lists under the retired spelling.
FILESYSTEM_READ_TOOLS = (
    "read_file", "read_text_file", "read_multiple_files", "list_directory",
    "list_directory_with_sizes", "directory_tree", "get_file_info", "search_files",
)


def registry_spelled_filesystem_reads() -> frozenset[str]:
    """The filesystem read tools as the MCP registry registers them."""
    from tools.mcp_tool_schema import mcp_prefixed_tool_name

    return frozenset(mcp_prefixed_tool_name("filesystem", name) for name in FILESYSTEM_READ_TOOLS)


def add_registry_spelled_filesystem_reads() -> None:
    """Rebind upstream's idempotent set to include the registry spellings (idempotent)."""
    from agent import tool_guardrails

    current = tool_guardrails.IDEMPOTENT_TOOL_NAMES
    wanted = registry_spelled_filesystem_reads()
    if not wanted <= current:
        tool_guardrails.IDEMPOTENT_TOOL_NAMES = frozenset(current | wanted)
