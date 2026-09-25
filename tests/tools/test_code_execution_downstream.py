"""Fork-owned tests moved out of ``tests/tools/test_code_execution.py`` (lane MOVE-A).

Same names, same bodies: the ``code`` parameter's import examples, which the fork
covered when its brief replaced upstream's per-tool description. The brief itself
is tested against the wire middleware in ``tests/tools/test_downstream_schema.py``.
"""

import unittest

from tools.code_execution_tool import SANDBOX_ALLOWED_TOOLS, build_execute_code_schema


class TestBuildExecuteCodeSchemaDownstream(unittest.TestCase):
    def test_import_examples_prefer_web_search_and_terminal(self):
        enabled = {"web_search", "terminal", "read_file"}
        schema = build_execute_code_schema(enabled)
        code_desc = schema["parameters"]["properties"]["code"]["description"]
        self.assertIn("web_search", code_desc)
        self.assertIn("terminal", code_desc)

    def test_import_examples_fallback_when_no_preferred(self):
        """When neither web_search nor terminal are enabled, falls back to
        sorted first two tools."""
        enabled = {"read_file", "write_file", "patch"}
        schema = build_execute_code_schema(enabled)
        code_desc = schema["parameters"]["properties"]["code"]["description"]
        # Should use sorted first 2: patch, read_file
        self.assertIn("patch", code_desc)
        self.assertIn("read_file", code_desc)

    def test_empty_set_produces_valid_description(self):
        """build_execute_code_schema(set()) must not produce 'import , ...'
        in the code property description."""
        schema = build_execute_code_schema(set())
        code_desc = schema["parameters"]["properties"]["code"]["description"]
        self.assertNotIn("import , ...", code_desc,
                         "Empty enabled set produces broken import syntax in description")

    def test_real_scenario_all_sandbox_tools_disabled(self):
        """Reproduce the exact code path from model_tools.py:231-234.

        Scenario: user runs `hermes tools code_execution` (only code_execution
        toolset enabled). tools_to_include = {"execute_code"}.

        model_tools.py does:
            sandbox_enabled = SANDBOX_ALLOWED_TOOLS & tools_to_include
            dynamic_schema = build_execute_code_schema(sandbox_enabled)

        SANDBOX_ALLOWED_TOOLS = {web_search, web_extract, read_file, write_file,
                                  search_files, patch, terminal}
        tools_to_include  = {"execute_code"}
        intersection      = empty set
        """
        # Simulate model_tools.py:233
        tools_to_include = {"execute_code"}
        sandbox_enabled = SANDBOX_ALLOWED_TOOLS & tools_to_include

        self.assertEqual(sandbox_enabled, set(),
                         "Intersection should be empty when only execute_code is enabled")

        schema = build_execute_code_schema(sandbox_enabled)
        code_desc = schema["parameters"]["properties"]["code"]["description"]
        self.assertNotIn("import , ...", code_desc,
                         "Bug: broken import syntax sent to the model")

    def test_real_scenario_only_vision_enabled(self):
        """Another real path: user runs `hermes tools code_execution,vision`.

        tools_to_include = {"execute_code", "vision_analyze"}
        SANDBOX_ALLOWED_TOOLS has neither, so intersection is empty.
        """
        tools_to_include = {"execute_code", "vision_analyze"}
        sandbox_enabled = SANDBOX_ALLOWED_TOOLS & tools_to_include

        self.assertEqual(sandbox_enabled, set())

        schema = build_execute_code_schema(sandbox_enabled)
        code_desc = schema["parameters"]["properties"]["code"]["description"]
        self.assertNotIn("import , ...", code_desc)
