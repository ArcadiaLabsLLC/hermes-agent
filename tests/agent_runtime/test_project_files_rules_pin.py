"""hermes' reader keeps the rule spec's values exactly as the vendored ``rules.json`` says.

Eternia's ``spec/rules.json`` owns every value; ``agent_runtime/project_files/rules.py`` keeps
them as constants for the reader. This pins one to the other, so a value changed in Eternia
and vendored here reds until the reader follows (row
``MC-PHONE-FILES-BOTH-LOCAL-READERS-FOLLOW-ONE-RULE-SPEC``).

Killing mutation (2026-11-21, w1118a-spec): ``MAX_READ_BYTES = 5 * 1024 * 1024 + 1`` ->
``test_reader_constants_match_the_spec`` red naming ``max_read_bytes``.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.project_files import rules
from scripts.vendor_launcher_catalog import FILE_TREE_SPEC

pytestmark = pytest.mark.gate


def test_reader_constants_match_the_spec():
    spec = json.loads((FILE_TREE_SPEC / "rules.json").read_text(encoding="utf-8"))
    verbs = spec["verbs"]
    pairs = {
        "path_grammar.max_length": (spec["path_grammar"]["max_length"], rules.MAX_PATH_LENGTH),
        "never_listed_or_read": (spec["ignore"]["never_listed_or_read"], list(rules.NEVER_LISTED)),
        "skip_directories": (spec["ignore"]["skip_directories"], list(rules.SKIP_DIRECTORIES)),
        "max_read_bytes": (spec["size_and_type"]["max_read_bytes"], rules.MAX_READ_BYTES),
        "binary_probe_bytes": (spec["size_and_type"]["binary_probe_bytes"], rules.BINARY_PROBE_BYTES),
        "tree.default_depth": (verbs["tree"]["default_depth"], rules.DEFAULT_DEPTH),
        "tree.max_depth": (verbs["tree"]["max_depth"], rules.MAX_DEPTH),
        "tree.max_entries": (verbs["tree"]["max_entries"], rules.MAX_ENTRIES),
        "read.page_code_points": (verbs["read"]["page_code_points"], rules.READ_PAGE_CODE_POINTS),
        "grep.min_pattern": (verbs["grep"]["min_pattern"], rules.MIN_PATTERN),
        "grep.max_pattern": (verbs["grep"]["max_pattern"], rules.MAX_PATTERN),
        "grep.max_matches": (verbs["grep"]["max_matches"], rules.MAX_MATCHES),
        "grep.line_code_points": (verbs["grep"]["line_code_points"], rules.LINE_CODE_POINTS),
        "refusals": (list(spec["refusals"]), list(rules.REFUSAL_CODES)),
        "write_ops": (spec["write_ops"], list(rules.WRITE_OPS)),
    }
    drifted = [name for name, (want, have) in pairs.items() if want != have]
    assert not drifted, f"the reader's rules drifted from the vendored spec: {drifted}"
