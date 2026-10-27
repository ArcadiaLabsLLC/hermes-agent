#!/usr/bin/env python3
"""Course authoring persona tools — the registrar for ``agent_runtime.course_tool`` (RT-COURSE-PERSONA-TOOLS).

``course_checkout`` / ``course_commit`` / ``course_pull_request`` in the ``course`` toolset, which the
fork's ``harness_core`` composite includes. Registered here, as a builtin beside ``board_tool``, so the
toolset is in the committed manifest (``tools/toolset_manifest.json``) and a declaration read that expands
``harness_core`` never has to discover plugins to know it. The behaviour lives in
``agent_runtime/course_tool.py``; the handlers are lambdas HERE so a handler's module is the module that
registered it (``board_tool``'s shape).
"""

from agent_runtime import course_tool
from tools.registry import registry

registry.register(
    name="course_checkout",
    toolset="course",
    schema=course_tool.COURSE_CHECKOUT_SCHEMA,
    handler=lambda args, **kw: course_tool.handle_course_checkout(args, **kw),
    description="Clone or fetch a course repo with the turn's course credential.",
    emoji="📚",
)

registry.register(
    name="course_commit",
    toolset="course",
    schema=course_tool.COURSE_COMMIT_SCHEMA,
    handler=lambda args, **kw: course_tool.handle_course_commit(args, **kw),
    description="Commit and push files on the persona's course authoring branch.",
    emoji="📚",
)

registry.register(
    name="course_pull_request",
    toolset="course",
    schema=course_tool.COURSE_PULL_REQUEST_SCHEMA,
    handler=lambda args, **kw: course_tool.handle_course_pull_request(args, **kw),
    description="Open the pull request for the persona's course authoring branch.",
    emoji="📚",
)
