"""The TABLES: the probe-backed env-gap registry, the web-build prerequisite files, the known defects.

A table module (floor-exempt) -- the file a lane edits to add a row. Every
``_ENV_GAP_SKIPS`` row names a live probe from ``probes``; ``tests/test_env_gap_registry.py``
fails a row whose probe stops describing a gap. The map is
``tests/_downstream/hermes_cli_conftest/__init__.py``.
"""

from __future__ import annotations

from tests._env_gap_fence import EnvGapSkipRegistry
from tests._downstream.hermes_cli_conftest.probes import (
    _no_module,
    _no_os_chown,
    _no_posix_mode_bits,
    _no_posix_privilege_api,
    _no_posix_wait_status,
    _no_shebang_script_execution,
    _posix_only_branch,
    _test_python_outside_project_venv,
    _unelevated_windows_shell,
)

#: The one-line reason the ``xfail`` mark on ``test_telegram_parity`` carries.
#: The mark (applied by id from ``tests/_downstream/id_markers/``, which
#: owns the text) and this banner share ONE string rather than restating it, so the fence and the report cannot drift apart into two
#: accounts of one defect — the register-rot shape C25 is about.
from tests._downstream.id_markers.reasons import TELEGRAM_PARITY_DEFECT_REASON  # noqa: E402 — single source, the table applies the mark

__layer__ = "stores"

# ── Prerequisite guard: files that execute the REAL web-UI build ───────────
#
# The two files below call `cmd_update` / `_cmd_update_impl` with only
# `subprocess.run` stubbed. Production's `_build_web_ui` reaches
# `_run_with_idle_timeout`, which uses `subprocess.Popen` — unstubbed — so the
# test performs a genuine `npm install` + `npm run build -w web` against the
# checkout. `web/package.json` pins `vite ^8`, whose engine floor is
# Node `^20.19.0 || >=22.12.0`. Below that floor the build cannot complete, the
# call blocks past the 30s per-test cap, and pytest-timeout's thread method
# kills the WHOLE process — taking every other result in the run with it. A
# marker cannot help: the hang is in a test the registry does not (and should
# not) list as a failure.
#
# This is an environment PREREQUISITE check, not a loosened assertion: on a
# host that meets the floor the guard is inert and both files run in full,
# executing every original assertion.
_WEB_BUILD_PREREQ_FILES = frozenset({
    "test_cmd_update.py",
})

_ENV_GAP_SKIPS: EnvGapSkipRegistry = {
    # ── Spawn shapes the loader does not support ──────────────────────────
    #
    # Registered 2026-08-10, when the shlex path-spelling defect that used to
    # be the FIRST cause of these two failures was fixed (agent/shell_hooks.py
    # now tokenizes through _split_command). Underneath it sat this second,
    # independent cause, which the fix does not touch: both tests write a bare
    # `#!/usr/bin/env bash` script and require `hermes hooks test` to actually
    # execute it. Their sibling TestHooksDoctor::test_flags_mtime_drift — the
    # node that pinned the tamper check — is NOT registered and now passes.
    'test_hooks_cli.py': [
        (
            _no_shebang_script_execution,
            'these two spawn a bare `#!/usr/bin/env bash` hook script through '
            'shell_hooks._spawn (shell=False, argv[0] = the .sh itself), and '
            'this loader cannot exec a shebang script — WinError 193. The hook '
            'machinery itself is platform-neutral: an interpreter-prefixed '
            'command (`python <path>.py`) runs here',
            {
                'TestHooksTest::test_fires_real_subprocess_and_parses_block',
                'TestHooksTest::test_synthetic_payload_matches_production_shape',
            },
        ),
    ],
    # ── POSIX-only syscalls: the mechanism is a missing attribute ──────────
    'test_container_boot.py': [
        (
            _no_os_chown,
            's6 container supervision is Linux-only; service_manager._mkdir_owned '
            'calls os.chown, which does not exist on this platform',
            {
                'test_profiles_default_subdir_is_skipped_with_warning',
                'test_register_service_overwrites_existing_slot',
                'test_registered_profile_has_finish_script',
            },
        ),
    ],
    'test_ensure_hermes_home_uid.py': [
        (
            _no_os_chown,
            'os.chown does not exist on this platform, and config.py:713 returns '
            '(None, None) from _resolve_hermes_uid_gid on win32 by design — the '
            'same guard the sibling TestSecureDirChown in this file already '
            'carries',
            {
                'TestChownToHermesUid::test_eperm_is_silently_swallowed',
                'TestResolveHermesUidGid::test_returns_parsed_values_when_both_set',
            },
        ),
    ],
    'test_service_manager.py': [
        (
            _no_os_chown,
            'os.chown does not exist on this platform and systemd units cannot '
            'be written; service_manager._mkdir_owned is the POSIX seam',
            {
                'test_s6_log_run_creates_leaf_as_hermes_without_chown',
                'test_seed_supervise_skeleton_creates_expected_layout',
            },
        ),
    ],
    'test_ensure_acp_launcher.py': [
        (
            _no_posix_privilege_api,
            'os.geteuid does not exist on this platform; _ensure_acp_launcher '
            'also returns early on win32 (update_cmd.py:2198), and chmod(0o555) '
            'cannot make an NTFS directory unwritable',
            {
                'test_unwritable_bin_dir_is_skipped',
            },
        ),
    ],
    'test_apply_profile_override.py': [
        (
            _no_module("pwd"),
            'sudo profile resolution reads the POSIX account database '
            '(the _resolve_sudo_user_profile_env closure inside '
            'hermes_cli._profile_bootstrap.apply_profile_override imports pwd '
            'behind an os.geteuid()==0 gate); the pwd module does not exist '
            'here',
            {
                'TestApplyProfileOverrideHermesHomeGuard::test_sudo_explicit_profile_resolves_invoking_users_profile',
            },
        ),
    ],
    'test_kanban_core_functionality.py': [
        (
            _no_posix_wait_status,
            '_classify_worker_exit decodes a raw POSIX wait status '
            '(os.WIFEXITED / WEXITSTATUS / WIFSIGNALED); the exit registry it '
            'reads is populated only by reap_worker_zombies, gated '
            'os.name != "nt"',
            {
                'test_protocol_violation_budget_not_consumed_by_other_failures',
            },
        ),
    ],
    'test_kanban_db.py': [
        (
            _no_posix_wait_status,
            'same _classify_worker_exit POSIX wait-status decode. NB the old '
            'row claimed this asserts "POSIX signal delivery to synthetic PIDs" '
            '— it does not; _pid_alive is stubbed and no signal is ever sent',
            {
                'test_rate_limit_exit_requeues_without_counting_failure',
            },
        ),
    ],
    # ── NTFS cannot express a POSIX file mode ──────────────────────────────
    'test_profiles.py': [
        (
            _no_posix_mode_bits,
            'asserts a 0o600 .env mode; this filesystem records only a '
            'read-only bit, so os.chmod(0o600) reads back as 0o666. SEE THE '
            'ESCALATION FILED WITH THIS CHANGE: profile .env files hold API '
            'keys and are genuinely NOT owner-restricted on Windows, which '
            'wants an ACL path rather than a skipped test',
            {
                'TestBackfillProfileEnvs::test_copies_default_env_into_envless_profiles',
                'TestCreateProfile::test_seeds_placeholder_env_file',
            },
        ),
    ],
    # ── absent modules ─────────────────────────────────────────────────────
    #
    # The croniter / pathspec / pywinpty rows that stood here were retired on
    # 2026-08-10 by INSTALLING those packages on this interpreter — see the
    # "broken install, not an environment gap" note in the audit block above.
    # Only the two genuinely-absent modules are left.
    'test_session_browse.py': [
        (
            _no_module("curses"),
            "the '_curses' extension is unavailable. Genuinely OPTIONAL, unlike "
            'the three retired dependency rows: windows-curses is deliberately '
            'not declared in pyproject.toml, and curses_ui.py:623-624 catches '
            'the ImportError and returns the numbered text fallback, so the '
            'pickers degrade by design rather than break. These two tests pin '
            'the curses branch specifically, which this host cannot select',
            {
                'TestCursesBrowse::test_escape_cancels',
                'TestCursesBrowse::test_type_to_filter_then_enter',
            },
        ),
    ],
    'test_web_ui_build.py': [
        (
            _no_module("fcntl"),
            'the flock test imports fcntl; main.py:5602-5605 explicitly falls '
            'through on ImportError ("Windows: no flock"), so the branch under '
            'test is unreachable here',
            {
                'TestBuildWebUIFlock::test_contended_lock_without_dist_waits_then_skips_fresh_build',
            },
        ),
    ],
    # ── the production code itself branches on sys.platform ────────────────
    'test_cmd_update.py': [
        (
            _posix_only_branch,
            'cmd_update prepends `git -c windows.appendAtomically=false` on '
            'win32 and resolves npm as npm.CMD; the mocks assert the POSIX '
            'argv. WARNING: this file only stubs subprocess.run, so '
            '_build_web_ui still runs a REAL npm install + vite build against '
            'the checkout — treat it as side-effecting',
            {
                'TestCmdUpdateBranchFallback::test_update_on_fork_checks_upstream_when_origin_up_to_date',
            },
        ),
    ],
    # ── Lane REDS3: live Windows E2Es whose premise is this box, not the code ──
    'test_venv_holder_windows_live.py': [
        (
            _test_python_outside_project_venv,
            'the sleepers are spawned from sys.executable, a shared test venv '
            'outside this checkout, and the holder scan reports only processes '
            'running from the project venv or checkout; run the file from an '
            'in-checkout .venv',
            {
                'TestDetection::test_detects_hermes_argv_process',
                'TestDetection::test_long_runtime_path_gateway_detected_with_full_argv',
                'TestClassification::test_pausable_exemption_sees_long_path_gateway',
                'TestClassification::test_serve_backend_not_classified_pausable',
                'TestHolderMessage::test_dashboard_not_labeled_desktop_backend',
                'TestHolderMessage::test_substring_subcommand_not_mislabeled',
            },
        ),
    ],
    'test_legacy_launchers_windows_live.py': [
        (
            _unelevated_windows_shell,
            'schtasks /Create answers "Access is denied" in an unelevated shell '
            '(class d-P); the test registers a real scheduled task',
            {
                'test_status_warns_and_uninstall_removes_pre_suffix_launchers',
            },
        ),
    ],
}



_KNOWN_DEFECTS: dict[str, str] = {
    "test_commands.py": (
        "KNOWN DEFECT — NOT an environment gap. Slack allows an app only 50\n"
        "  slash commands, and the registry no longer fits: 'platform' is a\n"
        "  gateway command on Telegram/Discord/CLI with NO native Slack slash,\n"
        "  so test_telegram_parity cannot pass. It is the only CANONICAL\n"
        "  casualty: every other name the cap drops is an alias whose\n"
        "  canonical spelling either still holds a native slot or is already a\n"
        "  deliberate _SLACK_VIA_HERMES_ONLY entry. (The exact casualty set\n"
        "  depends on which plugins are installed — the WARNING names them.)\n"
        "  The silence half of this finding is FIXED: the clamp is accounted\n"
        "  for at the one branch that performs it, slack_native_slashes() logs\n"
        "  every dropped name at WARNING, `hermes slack manifest` prints them\n"
        "  to stderr, and slack_clamped_slashes() returns the same list\n"
        "  (hermes_cli/commands.py). Visibility is not parity, though — naming\n"
        "  the casualty does not give /platform a slot, so the DEFECT STAYS.\n"
        "  It is now fenced as xfail(strict=True) rather than left as a\n"
        "  permanent red (ML-16 / B20(iv)): a file that can never be green has\n"
        "  no red left to spend on a REGRESSION, and the canonical per-file\n"
        "  runner's red definition could never be all-green while it stood.\n"
        "  strict is what keeps the fence honest — the day parity actually\n"
        "  holds, the test XPASSes and reds, and someone must come delete the\n"
        "  mark and this row. Fenced is not fixed.\n"
        "  Closing it means either pinning 'platform' a native slot (something\n"
        "  else then loses one) or declaring it Slack-via-/hermes in\n"
        "  _SLACK_VIA_HERMES_ONLY. Which commands get a native slot is product\n"
        "  curation, so it is an owner decision. The 50 is SLACK'S limit, not\n"
        "  ours — do not 'fix' this by raising it. Do NOT re-file this as\n"
        "  host_dependency_gap."
    ),
}
