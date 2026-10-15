"""Fork-owned tests moved out of ``tests/tools/test_execute_code_approval_cluster.py`` (lane CARRY).

Same names, same bodies; the upstream file is byte-identical to upstream.
"""

from __future__ import annotations

from tests.tools.test_execute_code_approval_cluster import (  # noqa: F401 — upstream names the moved tests use
    _register_resolver,
    gw_session,
)


def test_execute_code_refuses_when_approval_is_denied(gw_session, tmp_path):
    """THE guarantee, driven end to end: unapproved code does not run.

    ADDED 2026-08-09, replacing the behavioural half of what
    ``test_both_rpc_threads_use_propagation_helper`` was reaching for. That gate
    proved the approval PLUMBING was spelled a certain way in the source and
    proved nothing about whether unapproved code executes — the exact change it
    must catch (a restructure that skips the guard, or ignores its verdict)
    leaves the watched strings sitting untouched, and the gate stays green
    through an approval bypass. That is the class every issue in this file's
    header belongs to (#4146, #27303, #30882, #33057).

    So the refusal is driven against the real entry point: a gateway session
    that DENIES must make ``execute_code`` return a typed error and run nothing.

    The probe writes a file. That matters — a refusal asserted only on the
    returned JSON would pass against a guard that reports denial and executes
    anyway, which is precisely a bypass wearing a refusal's clothes.

    RED-PROOF: deleting the ``if not _guard.get("approved")`` early return in
    ``tools/code_execution_tool.py`` fails this test on the side-effect
    assertion, not merely on the status field.
    """

    import json as _json

    from tools import code_execution_tool as cet

    # "deny" is the resolver vocabulary the rest of this file uses ("once" /
    # "deny"); a dict here is silently NOT a denial, which is worth knowing —
    # the first draft of this test passed a dict, the guard did not read it as a
    # refusal, and the code RAN. That is the same shape as the bug being
    # guarded, arriving via the test rig.
    _register_resolver(gw_session, "deny")

    marker = tmp_path / "cluster_bypass_probe_should_never_run"
    raw = cet.execute_code(f"open({str(marker)!r}, 'w').write('executed')")
    result = _json.loads(raw)

    assert result["status"] == "error", (
        "execute_code did not refuse a DENIED approval — this is the bypass "
        f"class this file exists to guard. Returned: {result}"
    )
    assert result.get("tool_calls_made", 0) == 0, "denied code must not run"
    assert not marker.exists(), (
        "the denied code executed anyway — the guard's verdict was reported but "
        "not enforced"
    )
