"""Fork gateway policy, separate from upstream dispatch."""
from __future__ import annotations
from hermes_cli.config import cfg_get

def _needs_risk_assessor_warning(config: dict) -> bool:
    """Does this gateway run with manual approvals and no automated assessor?

    Startup heads-up (#30882): a gateway in manual approval mode with no
    automated risk assessor (tirith disabled AND no ``auxiliary.approval``
    model) can only gate dangerous commands / execute_code scripts via live
    in-chat approval, and those actions now fail closed rather than silently
    auto-running.

    Pulled out of ``GatewayRunner.__init__`` as a pure predicate so the
    condition is reachable from a unit test — the decision is unchanged.
    ``security.tirith_enabled`` is resolved through
    :mod:`hermes_cli.tirith_config`, the single authority for its default and
    its ``TIRITH_ENABLED`` override; reading it off the raw config with
    ``cfg_get`` (as this did) could not see the override, so a gateway whose
    operator had disabled scanning that way never got this heads-up.
    """
    from hermes_cli.tirith_config import tirith_enabled

    mode = str(
        cfg_get(config, "approvals", "mode", default="manual") or "manual"
    ).strip().lower()
    if mode != "manual":
        return False
    if tirith_enabled(config):
        return False
    return not cfg_get(config, "auxiliary", "approval", default=None)
