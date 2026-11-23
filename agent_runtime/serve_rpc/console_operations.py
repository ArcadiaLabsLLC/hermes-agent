"""Native twins of the Agent Console's local operations, behind existing owners."""
import re
from functools import partial

from agent_runtime.call_authorization import (
    CALLER_COMPUTER, CALLER_DEVICE, CALLER_LOCAL_CONSOLE, CALLER_STDIO_OWNER, COMPUTER_REACH_LOOK,
    TIER_CONSOLE, TIER_READ, is_computer_below_account,
)
from .protocol import err, ok, defer_or_inline, ERR_INVALID_PARAMS, ERR_NOT_FOUND, ERR_CONFLICT
from .registry import method
from agent_runtime.param_readers import read_text
from agent_runtime.permission_modes import SUPPORTED_PERMISSION_MODES
__layer__ = "lanes"


def _value_error(key: str, sentence: str) -> ValueError:
    return ValueError(key)


_console_text = partial(read_text, refuse=_value_error)


def _operation(rid, params, context, name, run):
    def execute():
        try:
            result = run(params)
            if result.get("ok") is False:
                return err(rid, ERR_CONFLICT, "The operation was refused.", result)
            import json
            if len(json.dumps(result, ensure_ascii=True)) > 900 * 1024:
                return err(rid, 4130, "This information is too large to display.",
                           {"reason": "response_too_large"})
            return ok(rid, result)
        except ValueError as exc:
            return err(rid, ERR_INVALID_PARAMS, "Invalid operation parameters.",
                       {"reason": "invalid_parameters", "field": str(exc)})
        except Exception as exc:
            return err(rid, ERR_CONFLICT, "The operation could not complete.",
                       {"reason": "operation_failed", "error_class": type(exc).__name__})
    return defer_or_inline(rid, name, context, execute)


def _console_model(params, instance):
    from hermes_cli.harness_parts.persona.model_and_skills_commands import model_operation_result
    _console_text(params, "persona_instance_id" if instance else "persona_id", required=True)
    for key in ("model", "provider", "reasoning_effort", "issued_at"):
        _console_text(params, key)
    if "use_default" in params and type(params["use_default"]) is not bool:
        raise ValueError("use_default")
    return model_operation_result(params, instance=instance)


@method("runtime.persona.instance.set_model", tier=TIER_CONSOLE)
def instance_model(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.instance.set_model", lambda p: _console_model(p, True))


@method("runtime.persona.set_model", tier=TIER_CONSOLE)
def persona_model(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.set_model", lambda p: _console_model(p, False))


def _context_switches(params):
    from hermes_cli.harness_parts.persona.context_memory_commands import CONTEXT_SWITCHES, context_operation_result
    _console_text(params, "persona_id", required=True)
    for key in CONTEXT_SWITCHES:
        if params.get(key) is not None and type(params[key]) is not bool:
            raise ValueError(key)
    return context_operation_result(params)


@method("runtime.persona.set_context", tier=TIER_CONSOLE)
def persona_context(rid, params, context=None):
    """Plan chat-lane-context-and-memory-gaps R1: ``persona set-context``'s wire twin."""
    return _operation(rid, params, context, "runtime.persona.set_context", _context_switches)


def _permission(params, preview):
    from hermes_cli.harness_parts.persona.inspect_commands import permission_operation_result
    for key in ("persona_id", "session_id"):
        _console_text(params, key, required=True)
    _console_text(params, "reason", required=not preview)
    _console_text(params, "expires_at")
    if params.get("mode") not in SUPPORTED_PERMISSION_MODES:
        raise ValueError("mode")
    for key in ("ttl_seconds", "turns"):
        if params.get(key) is not None and (type(params[key]) is not int or params[key] < 1):
            raise ValueError(key)
    return permission_operation_result(params, preview=preview)


@method("runtime.persona.permission.preview", tier=TIER_CONSOLE)
def permission_preview(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.permission.preview", lambda p: _permission(p, True))


@method("runtime.persona.permission.set", tier=TIER_CONSOLE)
def permission_set(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.permission.set", lambda p: _permission(p, False))


@method("runtime.prompt_context.show", tier=TIER_CONSOLE)
def prompt_context(rid, params, context=None):
    def read(p):
        from agent_runtime.prompt_observability import load_persisted_context_row
        _console_text(p, "context_id", required=True)
        result = load_persisted_context_row(p["context_id"])
        if result is None:
            return {"found": False, "context_id": p["context_id"]}
        return result
    return _operation(rid, params, context, "runtime.prompt_context.show", read)


@method("runtime.persona.instance.detail", tier=TIER_READ, computer=COMPUTER_REACH_LOOK)
def instance_detail(rid, params, context=None):
    def read(p):
        from agent_runtime.snapshot.details import persona_instance_detail_for_id
        _console_text(p, "instance_id", required=True)
        result = persona_instance_detail_for_id(p["instance_id"])
        if result is None:
            return {"found": False, "instance_id": p["instance_id"]}
        return _detail_for_caller(result, context.caller if context is not None else None)
    return _operation(rid, params, context, "runtime.persona.instance.detail", read)


@method("runtime.prompt_observability.agent", tier=TIER_READ, computer=COMPUTER_REACH_LOOK)
def prompt_observability_agent(rid, params, context=None):
    """One agent's ``prompt_observability`` section, built when its panel opens.

    Owner ruling 2026-11-22: the section leaves the agent-list frame and is built for one agent, on open. TIER_READ: the same
    exposure the frame section had. A miss is ``{"found": false, "instance_id": …}``."""
    def read(p):
        from agent_runtime.snapshot.details import prompt_observability_for_instance
        _console_text(p, "instance_id", required=True)
        result = prompt_observability_for_instance(p["instance_id"])
        if result is None:
            return {"found": False, "instance_id": p["instance_id"]}
        return _prompt_details_for_caller(result, context.caller if context is not None else None)
    return _operation(rid, params, context, "runtime.prompt_observability.agent", read)


# ── who may see where things live on this computer (RT-FU-A-LOOK-DEVICE-IS-SENT-THE-PATH-OF-AN-AGENTS-
# SETTINGS-FILE, review w1122d.6). The detail's ``tool_resolution`` (and its ``turn_tool_context.preview``
# copy) names absolute local paths: the profile's config file, the turn's working directory, the runtime
# root, a bound repository. Only a caller at console reach keeps them; everyone else reads every label and
# source with the paths taken out. The stores, ``ToolsetDeclaration.row()`` and the local CLI keep theirs.
# The prompt details (RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-ITS-AGENTS-CONTEXT-FILES, review w1122d.12)
# name each context file (``path``) and each layer's file (``source_path``) the same way. The health check
# (``runtime_root``, ``hermes_home``, ``interpreter``, and the interpreter's path inside an ``issues`` sentence) and
# the agent list (each agent's ``profile_home``) return through ``_detail_for_caller`` too
# (RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-HERMES-BY-ITS-HEALTH-CHECK-AND-AGENT-LIST, review w1122d.13).

#: The keys that hold an absolute local path, read off ``tool_visibility.resolve_tool_visibility`` (``workdir``,
#: ``runtime_root``, ``repo_scope``), ``ToolsetDeclaration.row()`` and ``DeclarationIssue.row()`` (``config_path``),
#: the prompt details' context-file rows and workspace receipt (``path``) and their layers (``source_path``),
#: ``provider_health.provider_health_for_personas`` (``interpreter``, ``runtime_root``, ``hermes_home``) and
#: ``instance_catalog._project`` (``profile_home``). ``repo_scope`` may instead hold a portable label, which is kept.
_LOCAL_PATH_FIELDS = frozenset({"config_path", "root_config_path", "workdir", "runtime_root", "repo_scope",
                                "path", "source_path", "interpreter", "hermes_home", "profile_home"})
#: An absolute path as a value: POSIX, home-relative, a Windows drive or a UNC share.
_ABSOLUTE_PATH = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\]|\\\\)")
#: An absolute path inside prose (an issue's summary names its file): not after a word, a dot or a colon,
#: so ``chat/acp``, ``./x`` and a URL's ``//`` are left alone.
_PATH_IN_PROSE = re.compile(r"(?<![\w.:/\\])(?:~[/\\]|[A-Za-z]:[/\\]|/(?=[\w.~-]))[^\s'\"`,;()<>]*")
_PATH_WORDS = "a file on the agent's computer"


def _sees_local_paths(caller) -> bool:
    """Is *caller* at console reach: the owner's own console, a console device, a computer at the account level?

    ``None`` is an in-process call with no wire behind it. Every other caller (a view-only device, a computer at
    Look or Run chats, a caller the transport could not place) is projected."""

    if caller is None or caller.kind in (CALLER_STDIO_OWNER, CALLER_LOCAL_CONSOLE):
        return True
    if caller.kind == CALLER_DEVICE:
        return caller.device_tier == TIER_CONSOLE
    return caller.kind == CALLER_COMPUTER and not is_computer_below_account(caller)


def _detail_for_caller(result: dict, caller) -> dict:
    """The detail as *caller* may see it: below console reach, no absolute local path in any field or sentence."""

    # MUTATION: return ``result`` here for every caller and test_no_absolute_local_path_reaches_look_or_view_only
    # reddens, while test_the_console_keeps_the_paths stays green.
    if _sees_local_paths(caller):
        return result
    return _without_local_paths(result, _text_without_paths)


def _prompt_details_for_caller(result: dict, caller) -> dict:
    """One agent's prompt details as *caller* may see it: below console reach, no absolute path in a path field.

    Its text is left whole: a context file's ``preview`` and a layer's ``content`` are the file's and the rules'
    own words, which Look shares; only the detail's hermes-written sentences are rewritten (``_detail_for_caller``)."""

    # MUTATION: return ``result`` here for every caller and test_a_look_computer_reads_no_context_file_path
    # reddens, while test_the_console_keeps_the_context_file_paths stays green.
    if _sees_local_paths(caller):
        return result
    return _without_local_paths(result, _unchanged)


def _without_local_paths(node, text):
    """*node* (a JSON value) with every absolute local path field nulled and each string passed to *text*,
    routed by its JSON type."""

    return _PROJECTION_BY_TYPE.get(type(node), _leaf)(node, text)


def _object_without_paths(node: dict, text) -> dict:
    return {key: None if key in _LOCAL_PATH_FIELDS and _is_absolute_path(value)
            else _without_local_paths(value, text) for key, value in node.items()}


def _array_without_paths(node: list, text) -> list:
    return [_without_local_paths(item, text) for item in node]


def _string(node: str, text) -> str:
    return text(node)


def _leaf(node, text):
    return node


def _text_without_paths(node: str) -> str:
    # MUTATION: return ``node`` unchanged and test_an_issue_sentence_names_no_local_path reddens.
    return _PATH_IN_PROSE.sub(_PATH_WORDS, node)


def _unchanged(node: str) -> str:
    return node


_PROJECTION_BY_TYPE = {dict: _object_without_paths, list: _array_without_paths, str: _string}


def _is_absolute_path(value) -> bool:
    return isinstance(value, str) and _ABSOLUTE_PATH.match(value) is not None


@method("runtime.skills.catalog", tier=TIER_READ)
def skills_catalog(rid, params, context=None):
    def read(p):
        from agent_runtime.prompt_observability import skills_catalog_by_hash
        from agent_runtime.snapshot.details import materialize_prompt_skills_catalogs
        _console_text(p, "content_hash", required=True)
        result = skills_catalog_by_hash(p["content_hash"], materialize=materialize_prompt_skills_catalogs)
        return {"hash": p["content_hash"], "found": result is not None, "skills": result or []}
    return _operation(rid, params, context, "runtime.skills.catalog", read)


def _toolset_persona(params):
    """The persona ``params["persona_id"]`` names, or ``None`` when the store has none."""
    from agent_runtime.store import AgentStore
    try:
        return AgentStore().get(params["persona_id"])
    except (FileNotFoundError, KeyError):
        return None


def _toolset_approve(params):
    """Grant or revoke one persona's opt-in to a bundled-disabled toolset (``agent_runtime/bundled_toolsets``).

    The bundled edition writes the record; the Developer Edition answers ``edition_not_bundled``. A typed
    refusal is ``data.reason``; the reply carries the persona's ``toolset_approvals`` after the write."""
    import logging

    from agent_runtime import bundled_toolsets as bt
    for key in ("persona_id", "toolset"):
        _console_text(params, key, required=True)
    _console_text(params, "reason")
    if params.get("mode") not in tuple(bt.Mode):
        raise ValueError("mode")
    persona = _toolset_persona(params)
    if persona is None:
        return {"ok": False, "reason": "persona_not_found", "persona_id": params["persona_id"]}
    home = bt.persona_home(persona)
    try:
        bt.write_approval(home, params["toolset"], mode=params["mode"], reason=params.get("reason") or "",
                          granted_by="operator")
    except bt.ToolsetApprovalRefused as refused:
        return {"ok": False, "reason": refused.reason.value, "toolset": params["toolset"]}
    logging.getLogger(__name__).info("persona.toolset_approved persona_id=%s toolset=%s mode=%s",
                                     params["persona_id"], params["toolset"], params["mode"])
    return {"persona_id": params["persona_id"], "toolset": params["toolset"], "mode": params["mode"],
            "toolset_approvals": [str(row["toolset"]) for row in bt.read_approvals(home)]}


@method("runtime.persona.toolset.approve", tier=TIER_CONSOLE)
def toolset_approve(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.toolset.approve", _toolset_approve)


def _toolset_list(params):
    """The opt-in toolsets this edition offers one persona, each granted or not (the approve verb's read).

    The Developer Edition offers none and says so with ``edition_not_bundled: true``; an unknown persona
    is the approve verb's ``persona_not_found`` refusal."""
    from agent_runtime import bundled_toolsets as bt
    _console_text(params, "persona_id", required=True)
    persona = _toolset_persona(params)
    if persona is None:
        return {"ok": False, "reason": "persona_not_found", "persona_id": params["persona_id"]}
    bundled = bt.edition_bundled()
    offers = bt.toolset_offers(bt.persona_home(persona)) if bundled else ()
    return {"persona_id": params["persona_id"], "edition_not_bundled": not bundled, "toolsets": list(offers)}


@method("runtime.persona.toolset.list", tier=TIER_CONSOLE)
def toolset_list(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.toolset.list", _toolset_list)


# ── persona and skills: the argv verbs Eternia ran as a command line (RT-EVERY-ACTION-ETERNIA-SENDS-HAS-A-TYPED-
# CALL-ON-THE-RUNNING-HERMES). Each runs the argv handler's own code through the operation-result sink, so the
# store write, the refusals and the reply are that verb's; ``ok: false`` answers 4090 with the payload as data.

_UPDATE_PROFILE_PARAMS = frozenset({"persona_instance_id", "display_name", "current_chat_goal", "goal_id",
                                    "skills", "clear_skills", "inherit_skills"})
_SET_SKILLS_PARAMS = frozenset({"persona_id", "skills", "clear_skills", "issued_at"})


def _exact(params, allowed):
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ValueError(unknown[0])


def _skill_list(params):
    """``skills``: absent/null (no opinion) or a list of id strings — never a bare string, which the argv
    path would have read as one skill per flag."""
    raw = params.get("skills")
    if raw is None:
        return
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError("skills")


def _flags(params, *names):
    for name in names:
        if name in params and type(params[name]) is not bool:
            raise ValueError(name)


def _update_profile(params):
    from hermes_cli.harness_parts.persona.instance_commands import update_profile_operation_result

    _exact(params, _UPDATE_PROFILE_PARAMS)
    _console_text(params, "persona_instance_id", required=True)
    for key in ("display_name", "goal_id"):
        _console_text(params, key)
    # A blank goal is a deliberate clear (the store keeps "" as no goal), so it is text, empty allowed.
    _console_text(params, "current_chat_goal")
    _skill_list(params)
    _flags(params, "clear_skills", "inherit_skills")
    return update_profile_operation_result(params)


@method("runtime.persona.instance.update_profile", tier=TIER_CONSOLE)
def instance_update_profile(rid, params, context=None):
    """``harness persona instance update-profile``'s twin: ``{persona_instance_id, display_name?,
    current_chat_goal?, goal_id?, skills?: [id], clear_skills?, inherit_skills?}`` -> the argv payload
    (``ok, persona_instance_id, persona_id, backing_profile, updated_instance, next_expected``). An absent
    ``skills`` leaves the overrides alone; ``[]`` is never sent for "no opinion"."""
    return _operation(rid, params, context, "runtime.persona.instance.update_profile", _update_profile)


def _persona_template_skills(params):
    from hermes_cli.harness_parts.persona.model_and_skills_commands import set_skills_operation_result

    _exact(params, _SET_SKILLS_PARAMS)
    _console_text(params, "persona_id", required=True)
    _console_text(params, "issued_at")
    _skill_list(params)
    _flags(params, "clear_skills")
    return set_skills_operation_result(params)


@method("runtime.persona.set_skills", tier=TIER_CONSOLE)
def persona_set_skills(rid, params, context=None):
    """``harness persona set-skills``'s twin: ``{persona_id, skills?: [id], clear_skills?, issued_at?}`` -> the
    argv payload (``ok, status, applied, changed, scope, cleared, persona_id, applied_to_persona_id, skills,
    unresolved, persistence, next_expected``). Its typed refusals (``nothing_to_write``, ``conflicting_args``,
    ``persona_not_found`` …) ride the 4090 payload."""
    return _operation(rid, params, context, "runtime.persona.set_skills", _persona_template_skills)


def _skills_sync(params):
    from dataclasses import asdict

    from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
    from agent_runtime.skill_install import install_harness_skills, install_harness_skills_for_personas

    _exact(params, frozenset({"active_profile_only"}))
    _flags(params, "active_profile_only")
    if params.get("active_profile_only"):
        results = install_harness_skills()
    else:
        results = install_harness_skills_for_personas(ensure_persisted_personas(load_agent_runtime_config()))
    # ``ok`` is a RESULT here, never the refusal flag: a skill that failed to install is reported per row.
    return {"installed": [asdict(result) for result in results], "all_ok": all(result.ok for result in results)}


@method("runtime.harness.skills.sync", tier=TIER_CONSOLE)
def harness_skills_sync(rid, params, context=None):
    """``harness install-harness-skills``'s twin: ``{active_profile_only?}`` -> ``{installed: [{skill, changed,
    ok, …}], all_ok}``. Rewrites this machine's installed Harness skill copies, so local console only."""
    return _operation(rid, params, context, "runtime.harness.skills.sync", _skills_sync)


def _flow_apply(params):
    import json

    from agent_runtime.flow_graph import FlowGraphDocError, ingest_flow_graph

    _exact(params, frozenset({"graph"}))
    graph = params.get("graph")
    if isinstance(graph, dict):
        text = json.dumps(graph)
    elif isinstance(graph, str) and graph.strip():
        text = graph
    else:
        raise ValueError("graph")
    try:
        return ingest_flow_graph(text, requested_by="operator")
    except FlowGraphDocError as exc:
        return {"ok": False, "reason": "invalid_flow_graph", "error": str(exc)}


@method("runtime.flow.apply", tier=TIER_CONSOLE)
def flow_apply(rid, params, context=None):
    """``harness flow set --graph``'s twin: ``{graph: {graph_id, nodes, edges, …} | JSON text}`` -> the ingest
    report (``graph_id, owner_instance_id, changed_count, failed_count, bound_agent_count, reconciled, …``). An
    invalid document stores nothing and answers 4090 ``invalid_flow_graph``. Local console only: no remote
    surface authors a flow map."""
    return _operation(rid, params, context, "runtime.flow.apply", _flow_apply)
