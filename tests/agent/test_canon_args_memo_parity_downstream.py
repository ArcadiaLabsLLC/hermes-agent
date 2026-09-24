"""Fork-owned half of ``tests/agent/test_canon_args_memo_parity.py``.

Upstream's ``test_json_loads_linear_not_quadratic`` calls ``monkeypatch.undo()`` mid-test, which unwinds the
shared per-test MonkeyPatch (the root conftest's hermetic pins included) and is
red under the fork's ``_shared_monkeypatch_pin_tripwire``; it is a skip row in
``tests/_downstream/id_markers.py``. This is the same test with the patch
in a scoped ``monkeypatch.context()``. Helpers and fixtures are upstream's,
imported by name.
"""

from __future__ import annotations

import copy
import json

import agent.conversation_loop as cl
from tests.agent.test_canon_args_memo_parity import (  # noqa: F401 — upstream names the moved tests use
    UNI,
    _clear_canon_cache,
    build_history,
    canonicalize_pass_OLD,
)


class TestComplexityProof:

    def test_json_loads_linear_not_quadratic(self, monkeypatch):
        """Deterministic perf proof: count json.loads invocations.

        Pre-fix logic: one loads per tool call PER ITERATION -> K(K+1)/2 for
        a K-tool-call session.  Fixed logic: one loads per UNIQUE argument
        string, ever -> K.  (Malformed arguments raise and are never
        memoized in EITHER implementation — covered in the parity tests —
        so this proof uses an all-valid history to compare exactly.)
        """
        n = 40
        history = build_history(n)
        # force every argument string valid so both implementations take
        # only the canonicalize path (repair path is parity-tested elsewhere)
        for m in history:
            if m.get("tool_calls"):
                fn = m["tool_calls"][0]["function"]
                fn["arguments"] = json.dumps({"name": fn["name"],
                                              "id": m["tool_calls"][0]["id"],
                                              "u": UNI})

        def counting_loads(counter):
            real_loads = json.loads

            def wrapper(*a, **kw):
                counter[0] += 1
                return real_loads(*a, **kw)
            return wrapper

        # OLD: quadratic — K(K+1)/2 loads over a K-iteration session
        old_counter = [0]
        with monkeypatch.context() as counting:
            counting.setattr(json, "loads", counting_loads(old_counter))
            for k in range(1, n + 1):
                canonicalize_pass_OLD(copy.deepcopy(history[: 2 * k]))
        assert old_counter[0] == n * (n + 1) // 2

        # NEW: linear — each unique string loaded exactly once, ever
        new_counter = [0]
        with monkeypatch.context() as counting:
            counting.setattr(json, "loads", counting_loads(new_counter))
            for k in range(1, n + 1):
                cl._canonicalize_api_tool_calls(copy.deepcopy(history[: 2 * k]))
        assert new_counter[0] == n

        # quadratic -> linear, by exact call count
        assert old_counter[0] == (n + 1) / 2 * new_counter[0]
