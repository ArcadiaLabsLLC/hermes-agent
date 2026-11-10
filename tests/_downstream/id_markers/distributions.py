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

from tests._downstream.id_markers.reasons import (
    __layer__,
    _NEEDS_ACP,
    _NEEDS_CHROME_DESKTOP_ENTRY,
    _NEEDS_NODE,
    _NEEDS_TMUX,
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
    # A system tool, not a distribution: the live classic-CLI tests type into tmux
    # (FH-HERMES-CLI-GATEWAY-UPDATE-REDS-REMAINDER: red `FileNotFoundError: 'tmux'` on the Linux box).
    "tests/hermes_cli/test_gateway_chat_native.py::test_native_classic_fresh_resume_and_oneshot": (_NEEDS_TMUX,),
    **{
        f"tests/hermes_cli/test_gateway_chat_commands_live.py::{node}": (_NEEDS_TMUX,)
        for node in (
            "test_classic_view_title_and_usage_match_main",
            "test_classic_view_retry_undo_new_match_main",
            "test_classic_view_plan_and_goal_run_on_the_gateway",
        )
    },
    # Host tools for upstream's desktop/web build tests (FH-LINUX-BOX-SCRIPTS-NEED-NODE): each
    # asserts or spawns `node` and reds `assert None` / exit 127 on a box without it.
    "tests/scripts/test_bundle_npm.py::test_bundle_npm_runs_workspace_from_unrelated_directory": (_NEEDS_NODE,),
    "tests/scripts/test_desktop_build_cache.py::"
    "test_restored_npm_cache_installs_offline_and_excludes_job_secrets": (_NEEDS_NODE,),
    "tests/scripts/test_agent_build.py::test_payload_smoke_uses_relocated_manifest_commands": (_NEEDS_NODE,),
    "tests/scripts/test_source_build_env.py::"
    "test_posix_build_children_stamp_old_and_new_without_changing_parent[node]": (_NEEDS_NODE,),
    "tests/scripts/test_source_driver.py::"
    "test_pm_observer_accepts_ready_fixture_and_leaves_failed_fixture_untouched": (_NEEDS_NODE,),
    # Node rows, not the file: the file already carries fork_marks' timeout row (one class per key).
    **{
        f"tests/scripts/test_icon_flavors.py::{node}": (_NEEDS_NODE,)
        for node in (
            "test_canary_changes_only_desktop_background_preserving_art_and_native_geometry",
            "test_commit_icons_are_red_and_print_only_the_actual_seven_digit_prefix",
            "test_layered_macos_icon_mono_layer_and_flavor_stays_in_the_fill",
            "test_invalid_or_conflicting_build_identity_cannot_emit_icons",
            "test_msix_logos_resolve_every_slot_windows_draws",
        )
    },
    # Not Node: the shim's browser choice needs an installed google-chrome.desktop (reasons.py).
    **{
        f"tests/scripts/desktop_update/test_desktop_update_shim_profile_cleanup.py::"
        f"test_shim_removes_only_its_owned_profile[{outcome}]": (_NEEDS_CHROME_DESKTOP_ENTRY,)
        for outcome in ("success", "error")
    },
    "tests/acp_adapter/test_acp_dashboard_model_switch_validation.py": (_NEEDS_ACP,),
    "tests/acp_adapter/test_edit_approval.py::"
    "test_acp_permission_tool_call_uses_edit_kind_and_diff_content": (_NEEDS_ACP,),
    # Upstream v0.23.1 (ab3afc0b89, ec24dd3556) split the one refusal test into these five.
    **{
        f"tests/acp_adapter/test_failed_turn_closure.py::{node}": (_NEEDS_ACP,)
        for node in (
            "test_acp_refusal_never_poisons_the_next_prompt",
            "test_acp_refusal_is_erased_durably_and_survives_a_reload",
            "test_acp_exception_shaped_refusal_is_also_erased",
            "test_acp_refused_turn_stays_in_the_display_tagged_content_refused",
            "test_acp_reload_replays_the_refused_ask_and_notice_to_the_editor",
        )
    },
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
