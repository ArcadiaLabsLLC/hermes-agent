"""Rows gated on an OPTIONAL distribution -- retired by installing the extra.

A table module under the floor on purpose (folding it into ``fork_marks`` would
misfile "install the extra" under "a fork change"). ``REQUIRES_DISTRIBUTION`` is
read by ``hooks._skip_if_distribution_missing``.

One ``ROWS`` table, already host-filtered; ``hooks._merge`` concatenates the four.
The map is ``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import importlib.util

import pytest

from tests._downstream.id_markers.reasons import (  # noqa: F401
    _NEEDS_ACP,
)

__layer__ = "models"

ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = {
    # DEPENDENCY-bound: plugins/platforms/wecom/callback_adapter.py falls back
    # to ET=None without defusedxml; installing it retires these.
    **{
        f"tests/gateway/test_wecom_callback.py::{node}": (
            pytest.mark.skipif(
                importlib.util.find_spec("defusedxml") is None,
                reason="optional dependency 'defusedxml' is not installed",
            ),
        )
        for node in (
            "TestWecomCallbackEventConstruction::test_build_event_extracts_text_message",
            "TestWecomCallbackPollLoop::test_poll_loop_dispatches_handle_message",
        )
    },
    "tests/acp_adapter/test_acp_dashboard_model_switch_validation.py": (_NEEDS_ACP,),
    "tests/acp_adapter/test_edit_approval.py::"
    "test_acp_permission_tool_call_uses_edit_kind_and_diff_content": (_NEEDS_ACP,),
    "tests/acp_adapter/test_failed_turn_closure.py::"
    "test_acp_refusal_closes_the_turn_and_is_not_replayed_into_the_next_prompt": (_NEEDS_ACP,),
}


#: Test directories whose modules import an OPTIONAL distribution at import. The
#: canonical test venv is the live install plus a test runner, and the live
#: install does not carry these extras, so the modules cannot collect there.
#: The probe is the import spec: the day the distribution is installed, the
#: modules collect and run again, with nothing here to delete. Only a module
#: whose collection FAILED on exactly that missing import is skipped; the rest
#: of the directory runs.
REQUIRES_DISTRIBUTION: dict[str, tuple[str, str]] = {
    "tests/acp_adapter/": ("acp", "agent-client-protocol, extra [acp]"),
}
