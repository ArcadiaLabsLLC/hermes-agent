"""Stable downstream tool guidance, independent of upstream prompt layout.

The eternia-harness plugin renders these: the tool-conditional lines and the Windows
tooling hint as system-prompt sections, and the execution-guidance Safety sentence as an
``llm_request`` rewrite of the wire system text (:func:`rewrite_request_safety_sentence`).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

__layer__ = "models"

logger = logging.getLogger(__name__)

TOOL_DESCRIBE_GUIDANCE = (
    "Tool descriptions are brief. Before the first use of an unfamiliar tool, "
    "call tool_describe(<name>) to load its full documentation and parameter "
    "reference."
)

SHELL_TOOL_PREFERENCE_GUIDANCE = (
    "Prefer the native tools over shell equivalents: read_file (not "
    "cat/head/tail), search_files (not grep/rg/find/ls), patch (not sed/awk), "
    "write_file (not echo/heredoc). Reserve terminal for builds, installs, git, "
    "processes, and scripts."
)

CLARIFY_CHOICES_GUIDANCE = (
    "When using clarify with options, put each option only in the `choices` "
    "array — never enumerate them inside the question text (choices render as "
    "pickable rows)."
)

BROWSER_PRECONDITION_GUIDANCE = (
    "All browser_* tools require a prior browser_navigate; browser_click and "
    "browser_type also require a prior browser_snapshot."
)

SKILL_MANAGE_CONFIRM_GUIDANCE = "Confirm with the user before creating or deleting a skill."

WINDOWS_NATIVE_TOOLING_HINT = (
    "Windows-native tooling: your terminal is bash, but when a task genuinely "
    "needs PowerShell or cmd (a cmdlet, a `.ps1` script, a Windows-only CLI), "
    "invoke it as a program from bash — `powershell.exe -NoProfile -Command "
    "'<script>'` (or `pwsh` for PowerShell 7), or `cmd.exe /c '<command>'`. "
    "These are on PATH; quote the inner command so bash passes it through "
    "verbatim. Prefer plain POSIX for everything else."
)


#: Upstream's Safety bullet in ``OPENAI_MODEL_EXECUTION_GUIDANCE`` — the rewrite's sentinel.
UPSTREAM_SAFETY_SENTENCE = (
    "- Safety: if the next step has side effects (file writes, commands, API calls), "
    "confirm scope before executing.\n"
)

#: The fork's Safety bullet: confirmation gates on destructiveness, not on side effects
#: (a persona ended its turn on a permission request for a clear order, 2026-08-03).
SAFETY_SENTENCE = (
    "- Safety: confirm scope before executing ONLY when the next step is destructive "
    "or hard to reverse (deleting or overwriting data, rewriting history, "
    "force-pushing, spending money). Routine tool use in service of a clear "
    "instruction — reads, edits, commands, and API calls the request plainly implies "
    "— proceeds without asking.\n"
)

# The guidance block the sentence lives in; present without the sentinel = upstream reworded it.
_SAFETY_BLOCK_ANCHOR = "<verification>\nBefore finalizing your response:\n"
_SYSTEM_ROLES = frozenset({"system", "developer"})
_miss_warned = False


def rewrite_safety_sentence(text: Any) -> Optional[str]:
    """``text`` with upstream's Safety bullet replaced by the fork's, or None if unchanged.

    A text that carries the verification block but neither sentence means upstream
    reworded its bullet: ONE warning per process, and the text is left alone (fail-open,
    never a second guidance paragraph beside upstream's).
    """
    global _miss_warned
    if not isinstance(text, str):
        return None
    if UPSTREAM_SAFETY_SENTENCE in text:
        return text.replace(UPSTREAM_SAFETY_SENTENCE, SAFETY_SENTENCE)
    if _SAFETY_BLOCK_ANCHOR in text and SAFETY_SENTENCE not in text and not _miss_warned:
        _miss_warned = True
        logger.warning(
            "eternia-harness: upstream's execution-guidance Safety sentence was not found; "
            "the fork's wording was NOT applied (update agent_runtime.prompt_guidance.UPSTREAM_SAFETY_SENTENCE)")
    return None


def _rewrite_blocks(blocks: Any) -> Optional[list]:
    """A content-block list with each text block rewritten, or None if unchanged."""
    if not isinstance(blocks, list):
        return None
    out, changed = list(blocks), False
    for index, block in enumerate(blocks):
        if isinstance(block, dict):
            new = rewrite_safety_sentence(block.get("text"))
            if new is not None:
                out[index], changed = {**block, "text": new}, True
    return out if changed else None


def _rewrite_content(content: Any) -> Any:
    """Rewritten string or block list, or None if unchanged."""
    return rewrite_safety_sentence(content) if isinstance(content, str) else _rewrite_blocks(content)


def rewrite_request_safety_sentence(request: Any) -> Optional[Dict[str, Any]]:
    """The provider kwargs with the Safety bullet rewritten in the system text, or None.

    Covers the three api modes' system slots: chat ``messages`` / Responses ``input`` (system and
    developer roles),
    Anthropic ``system`` (string or text blocks) and Responses ``instructions``. The
    original request is never mutated — upstream hands every callback the same object.
    """
    if not isinstance(request, dict):
        return None
    updates: Dict[str, Any] = {}
    for key in ("system", "instructions"):
        new = _rewrite_content(request.get(key))
        if new is not None:
            updates[key] = new
    for key in ("messages", "input"):  # chat messages; a Responses ``input`` item list
        messages = request.get(key)
        if not isinstance(messages, list):
            continue
        out, changed = list(messages), False
        for index, message in enumerate(messages):
            if isinstance(message, dict) and message.get("role") in _SYSTEM_ROLES:
                new = _rewrite_content(message.get("content"))
                if new is not None:
                    out[index], changed = {**message, "content": new}, True
        if changed:
            updates[key] = out
    return {**request, **updates} if updates else None
