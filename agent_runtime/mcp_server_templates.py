"""Canonical MCP server templates, and the readiness scope that validates configured blocks.

Moved out of :mod:`agent_runtime.machine_roots` (row RT-MACHINE-ROOTS-SIZE-CEILING) so that module
keeps the registry and the path-token chokepoint. The binding half of an MCP server's readiness —
token expansion and the platform gate — stays there (:func:`~agent_runtime.machine_roots.resolve_mcp_servers`);
this module owns what a correct block looks like and joins the two into :func:`mcp_server_issues`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any

from .machine_roots import ISSUE_MCP_TEMPLATE_DRIFT, MachineRoots, PathTokenIssue, resolve_mcp_servers

__layer__ = "models"


# ── Canonical MCP server templates ──────────────────────────────────────────
#
# A capability that every profile declares should be declared the SAME WAY. It
# was not: nine profiles carry a ``launcher_qa`` block and they had split into
# two variants — one that sets ``STAGEC_LAUNCH_HELPER`` explicitly (alice, base,
# neko, unbounded) and one that omits it (backend-dev, gpt-launcher,
# launcher-dev, launcher-qa, qa). The omission was SILENT rather than broken:
# the Launcher's ``launch_manager.dart`` falls back to the same helper path, so
# both variants behave identically today. That is exactly what makes it debt —
# the two blocks are only equivalent by coincidence of a fallback living in
# another repo, and nothing here could tell you which one was intended.
#
# Operator ruling (2026-07-31): the EXPLICIT variant is canonical. The template
# below is the source of truth; drift from it is reported as a typed issue on
# the existing readiness lane. Nothing in this module rewrites a config — the
# single config writer stays upstream ``save_config``, and this lane is
# report-only by construction (it has no write path to call).


def _freeze(value: Any) -> Any:
    """Deep-immutable view of a plain config literal.

    A module-level template that any caller can mutate is not a source of truth.
    Mappings become read-only proxies and sequences become tuples, so a consumer
    that tries to "just tweak one field" fails loudly at the mutation instead of
    silently redefining canonical for the rest of the process.
    """

    if isinstance(value, MappingProxyType):
        # Already frozen — return the SAME object so a template composed of
        # other templates keeps one identity per canonical block.
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


#: The persona seed's line 1 value for ``mcp_servers.<s>.env.HERMES_HOME``
#: (interpolated by ``_load_mcp_config`` from ``os.environ``). Defined HERE, the
#: lower layer, so the canonical template and the seed writer
#: (:mod:`agent_runtime.persona_seed_defaults`, which imports it) name one value:
#: a seeded profile matches the template with zero drift by construction
#: (RT-MCP-TEMPLATE-VS-SEED-HERMES-HOME).
MCP_HERMES_HOME_VALUE = "${HERMES_HOME}"

CANONICAL_LAUNCHER_QA_MCP_SERVER: Mapping[str, Any] = _freeze(
    {
        "command": (
            r"${roots.eternia_launcher}\tool\stagec_qa_mcp_server\build"
            r"\stagec_qa_mcp_server${exe_suffix}"
        ),
        "args": [],
        "env": {
            "STAGEC_QA_REPO_ROOT": "${roots.eternia_launcher}",
            "STAGEC_QA_TRANSPORT": "direct_control",
            "STAGEC_LAUNCH_HELPER": (
                r"${roots.eternia_launcher}\docs\stages\qa-reboot\scripts"
                r"\Start-StageCDirectExe.ps1"
            ),
            "STAGEC_SCREENSHOT_HELPER": (
                r"${roots.eternia_launcher}\docs\stages\qa-reboot\scripts"
                r"\Capture-StageCWindowScreenshot.ps1"
            ),
            "HERMES_HOME": MCP_HERMES_HOME_VALUE,
        },
        "platforms": ["windows"],
        "sampling": {"enabled": False},
        "connect_timeout": 60,
        "timeout": 260,
    }
)

CANONICAL_MCP_SERVER_TEMPLATES: Mapping[str, Mapping[str, Any]] = _freeze(
    {"launcher_qa": CANONICAL_LAUNCHER_QA_MCP_SERVER}
)


def canonical_mcp_server_template(name: str) -> Mapping[str, Any] | None:
    """The canonical block for ``name``, or ``None`` when none is defined."""

    return CANONICAL_MCP_SERVER_TEMPLATES.get(str(name))


def _normalize_for_diff(value: Any) -> Any:
    """Comparison form: key order irrelevant, path-token separators unified.

    Key order carries no meaning in YAML, and a tail written ``/tool/x`` resolves
    to the same file as ``\\tool\\x`` (``_join_tail`` splits on both). Comparing
    raw text would report drift for a config that is byte-different but
    resolution-identical — a false alarm the operator cannot act on.
    """

    if isinstance(value, Mapping):
        return {str(key): _normalize_for_diff(item) for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize_for_diff(item) for item in value]
    if isinstance(value, str) and "${" in value:
        return re.sub(r"[\\/]+", "/", value)
    return value


def _render(value: Any) -> str:
    normalized = _normalize_for_diff(value)
    if isinstance(normalized, str):
        return repr(normalized)
    return json.dumps(normalized, sort_keys=True)


def mcp_server_template_diffs(name: str, cfg: Any) -> list[str]:
    """Field-level differences between ``cfg`` and the canonical block for ``name``.

    Empty when no template is defined for the name or the block matches. Each
    row names ONE field with a dotted path, so the operator reads what to change
    rather than diffing two blobs by eye.
    """

    template = canonical_mcp_server_template(name)
    if template is None or not isinstance(cfg, Mapping):
        return []
    diffs: list[str] = []
    _diff_into(diffs, _normalize_for_diff(template), _normalize_for_diff(cfg), prefix="")
    return sorted(diffs)


def _diff_into(diffs: list[str], expected: Any, actual: Any, *, prefix: str) -> None:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        for key in sorted(set(expected) | set(actual)):
            field = f"{prefix}.{key}" if prefix else str(key)
            if key not in actual:
                diffs.append(f"{field}: missing (expected {_render(expected[key])})")
            elif key not in expected:
                diffs.append(f"{field}: unexpected ({_render(actual[key])})")
            else:
                _diff_into(diffs, expected[key], actual[key], prefix=field)
        return
    if expected != actual:
        where = prefix or "(root)"
        diffs.append(f"{where}: {_render(actual)} (expected {_render(expected)})")


def canonical_mcp_server_yaml(name: str, *, indent: int = 2) -> str:
    """The canonical block rendered as the YAML an operator would paste in.

    Emitted in fix hints and test failures so the correction is copy-pasteable
    rather than described. This module never applies it — see the section note.
    """

    template = canonical_mcp_server_template(name)
    if template is None:
        return ""
    pad = " " * indent
    lines = [f"{pad}{name}:"]
    _yaml_into(lines, template, indent=indent + 2)
    return "\n".join(lines)


def _yaml_into(lines: list[str], node: Mapping[str, Any], *, indent: int) -> None:
    pad = " " * indent
    for key in node:
        value = node[key]
        if isinstance(value, Mapping):
            lines.append(f"{pad}{key}:")
            _yaml_into(lines, value, indent=indent + 2)
        elif isinstance(value, (list, tuple)):
            if not value:
                lines.append(f"{pad}{key}: []")
            else:
                lines.append(f"{pad}{key}:")
                for item in value:
                    lines.append(f"{pad}  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{pad}{key}: {_yaml_scalar(value)}")


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    # SINGLE-quoted, always. These values are Windows paths full of backslashes,
    # and YAML's double-quoted style would read ``\t``/``\s`` as escapes — the
    # emitted "fix" would either fail to parse or silently install a different
    # path than the template. Single-quoted YAML has exactly one escape ('').
    return "'" + str(value).replace("'", "''") + "'"


def mcp_server_template_issues(
    servers: Mapping[str, Any],
    *,
    only: Iterable[str] | None = None,
) -> list[PathTokenIssue]:
    """Typed drift rows for every configured server that has a canonical template.

    Blocking, same as the binding failures :func:`mcp_server_issues` reports —
    see :data:`ISSUE_MCP_TEMPLATE_DRIFT`. Report-only: the rows name the fields
    and carry a pasteable block; no caller here writes a config.
    """

    wanted = {str(item) for item in only} if only is not None else None
    issues: list[PathTokenIssue] = []
    for name, cfg in servers.items():
        key = str(name)
        if wanted is not None and key not in wanted:
            continue
        diffs = mcp_server_template_diffs(key, cfg)
        if not diffs:
            continue
        issues.append(
            PathTokenIssue(
                code=ISSUE_MCP_TEMPLATE_DRIFT,
                field=f"mcp_servers.{key}",
                summary=(
                    f"MCP server '{key}' differs from the canonical template in "
                    f"{len(diffs)} field(s): " + "; ".join(diffs)
                ),
                fix_hint=(
                    f"Replace mcp_servers.{key} in this profile's config.yaml with the "
                    "canonical block below (under `mcp_servers:`). Report-only — no "
                    "config is rewritten:\n"
                    f"{canonical_mcp_server_yaml(key)}"
                ),
            )
        )
    return issues


# ── Readiness scoping: which configured blocks get validated ────────────────
#
# TWO scopes, ONE lane. The split is about what a finding MEANS:
#
# * CONFIGURED scope — a block that IS declared here and is wrong (drifted from
#   its canonical template, or carrying a path token that cannot bind on this
#   machine) is a defect no matter who requires it. The profile made the
#   declaration; readiness holds it to it.
# * REQUIRED scope — "this server is MISSING" is only meaningful against a
#   requirement. That class is not computed here at all: ``profile_readiness``
#   derives it from the required list, and it stays required-scoped. A profile
#   that simply does not declare an un-required server is not broken.
#
# Before 2026-08-01 BOTH classes were scoped to ``required``, which made the
# blocking drift check a runtime no-op on the live tree: every snapshot
# persona's required list is empty, so nothing was ever compared and the line
# was held only by the CI data test (ledger item 10, RULED: execute the
# widening).
#
# The configured scope is deliberately gated on "has a canonical template":
# those are the names this module can state a correct shape for. Widening the
# binding checks to EVERY configured block of every profile would turn an
# operator's unrelated experimental server into a readiness failure for a
# persona that never asked for it — a different ruling, not taken here.


def mcp_servers_in_issue_scope(
    servers: Mapping[str, Any],
    *,
    required: Iterable[str] | None = None,
) -> dict[str, Any]:
    """The configured blocks readiness validates, over the two scopes above.

    ``required=None`` means "no requirement context" — every configured block is
    in scope, which is what a caller handing over a specific map already means.
    """

    if required is None:
        return {str(name): cfg for name, cfg in servers.items()}
    wanted = {str(item) for item in required}
    return {
        str(name): cfg
        for name, cfg in servers.items()
        if str(name) in wanted or canonical_mcp_server_template(str(name)) is not None
    }


def mcp_server_issues(
    servers: Mapping[str, Any],
    *,
    required: Iterable[str] | None = None,
    roots: MachineRoots | None = None,
    check_target_exists: bool = True,
) -> list[PathTokenIssue]:
    """Typed reasons the configured MCP servers in scope are not usable here.

    Two kinds, one lane, one meaning: the block cannot BIND on this machine
    (unbound root, missing target, wrong platform), or it does not match its
    canonical template (:data:`ISSUE_MCP_TEMPLATE_DRIFT`). Drift used to be an
    opt-in extra because live configs still carried it; the five divergent
    profiles were canonicalized on 2026-08-01 and the opt-in was retired with
    them, so every caller now sees drift by default.

    ``required`` is a SCOPE, not a filter — it replaced the old ``only=``, which
    filtered honestly and, at the one readiness call site, filtered everything
    away. The required names are validated, and so is every configured block
    that has a canonical template — see :func:`mcp_servers_in_issue_scope`.
    """

    collected: list[PathTokenIssue] = []

    def _collect(_name: str, issue: PathTokenIssue) -> None:
        collected.append(issue)

    subset = mcp_servers_in_issue_scope(servers, required=required)
    resolve_mcp_servers(
        subset,
        roots=roots,
        on_issue=_collect,
        check_target_exists=check_target_exists,
    )
    collected.extend(mcp_server_template_issues(subset))
    return collected
