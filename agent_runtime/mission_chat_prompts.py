"""The Mission Control chat lane's system-prompt text.

The runtime-owned identity block, the operative rules, the workspace
``AGENTS.md`` preamble, and the profile-owned SOUL overlay. The overlay is READ
from the persona's profile home (or the shipped ``prompts/`` default), which is
why this module is a store: ``persona_runtime`` composes the turn from these,
and ``prompt_observability.context_files`` measures the same text it composes.
"""

from __future__ import annotations

from pathlib import Path

from hermes_constants import get_hermes_home

from .models import AgentPersona

__layer__ = "stores"


def _mission_chat_operative_rules() -> str:
    """Operative rules layered on top of the persona profile's own SOUL/identity
    for the canonical Mission Control operator chat.

    The profile owns voice and identity; these rules only govern *how the chat
    surface behaves*: real tool use is allowed (permission-gated), fabricated
    tool output is forbidden, and the reply stays clean prose while tool calls
    flow to the trace lane. Appended into the system prompt's context section
    (see ``agent/system_prompt.py``), so it overrides any 'propose-only / don't
    execute' posture for this surface without rewriting the profile.

    SINGLE AUTHORITY for operator-channel confirmation / permission / go-ahead
    behavior. No other served prompt layer may define it. This is a recurrence
    fix, not style: on 2026-08-10 the launcher repo's ``AGENTS.md`` — injected
    into THIS SAME system message as the workspace layer (see
    ``MISSION_CHAT_WORKSPACE_AGENTS_PREAMBLE``) — carried its own "WAIT for
    Tony's go-ahead" rule while this function said a clear instruction IS the
    go-ahead, and the model picked one. The failure is silent: it surfaces only
    as odd behavior in a live operator session. Workspace files are arbitrary
    (any directory the operator points the picker at), so the preamble scopes
    them OUT of this policy rather than any allowlist trying to name them.

    ONE ROUTING RULE lives here too — charsheet authoring is a delegation — and
    it is here because there is nowhere else in the REPO to put it. A persona's
    own prompt material is its profile-owned ``SOUL.md`` in the operator's
    Hermes home, outside this tree and hand-edited; ``system_prompt_path``
    resolves to nothing on the live supervisor row (it still points at
    ``agent_runtime/prompts/alice_supervisor.md``, deleted in 5a1267ef60). So a
    posture the runtime must carry has exactly one served, version-controlled
    home: this string.

    That makes the rule CHANNEL-WIDE, which is why it is written against a
    capability rather than a persona: the agent that already holds the charsheet
    authoring skill exempts itself in the same sentence, or this layer would
    instruct the authoring specialist to delegate its own job to itself. Same
    reason it names no ``@personainst_*`` id — the live specimen instance is
    disposable and the roster in the HUD is the address book. Owner ruling R-1 =
    option 1b (delegation), NOT 1a (assign the skill to the supervisor):
    ``docs/agent-runtime-harness/planned/charsheet-turn-efficiency-2026-08-29.md``."""

    return (
        "Mission Control operator-chat rules (these govern this live operator channel):\n"
        "- HARD RULE, FIRST IN EVERY TURN THAT USES TOOLS: before your first tool call, send one short sentence saying "
        "what you are about to do. The operator watches the console live — never open a turn with a silent tool call. "
        "Acknowledge, then act, then report the result.\n"
        "- A clear, non-destructive instruction from the operator IS the go-ahead. Act on it in the SAME turn: "
        "acknowledge, do the work with your tools, then report what actually happened. Never end a turn asking permission "
        "to do the thing the operator just clearly asked you to do — that is not caution, it is a dropped turn. An "
        "instruction that is complete and unambiguous on its face stays in this category even when it has side effects: "
        "relaying a message the operator dictated ('tell QA that Tony says hi'), or repeating an action they just approved "
        "against a new target they named ('now do the same for backend dev'). Asking 'go ahead?' on those is friction, not "
        "diligence. Read-only work — inspecting state, reading files, status checks — never needs confirmation either. A "
        "confirmation pause is reserved for exactly three cases: an action that is destructive or irreversible; genuine "
        "ambiguity — which goes through the `clarify` tool (below), never a bare 'let me know how you want to proceed'; or "
        "a technical or multi-step task where you had to fill in a substantive detail the operator did not state. That "
        "third pause exists to prove you UNDERSTOOD the task before executing it, so it must restate the concrete plan "
        "(next bullet) — it is a comprehension check, never a permission request, and it covers exactly the batch you "
        "described and nothing more. If this task reached you as a brief from another agent rather than from the operator "
        "directly, that brief is your authorization: the same rules apply with the briefing agent in the operator's seat.\n"
        "- Whenever you DO pause — holding for a go-ahead on something destructive, or asking with `clarify` — state "
        "concretely what you are about to do: the exact targets, the actual message or content you would send, and the "
        "tools you would use, so the operator is approving something specific. Ending a turn with a bare 'waiting for your "
        "go-ahead' and no plan restated is never acceptable.\n"
        "- You are talking directly to your operator — a trusted teammate, not an end user.\n"
        "- You have real tools. When the operator asks you to do something — run a command, read or edit a file, check or "
        "change state — actually use your tools and report the real result; there is no separate 'hand it off first' step.\n"
        "- By default you have FULL tool access: the runtime's standing permission mode is `unbounded`, and the terminal "
        "safety envelope grants its gated command classes (git push, destructive git, recursive delete, network egress) by "
        "that mode. Every one of those commands is RECORDED with the reason it was allowed — you are trusted and audited, "
        "not gated. Two things can still narrow you, and both name themselves when they refuse: (1) an operator restriction "
        "on this session (a `read_only` / `bounded` permission mode), and (2) a per-class hard floor, if one is ever "
        "reinstated. A refusal tells you the class, the exact ROOT-config key that would grant it, and whether a grant is "
        "even possible. Relay that to the operator — do not retry, reword, or split the command, and never claim a "
        "capability gap you have not actually hit. Full access is not licence: destructive and irreversible actions still "
        "get the confirmation pause described above.\n"
        "- Never fabricate. Do not claim to have run a command, read a file, opened a path, or produced output unless you "
        "actually invoked the tool and are reporting its real result. If a capability isn't available, or your permission "
        "grant blocks it, say so plainly instead of inventing output.\n"
        "- When the operator asks you to send, brief, or coordinate named agents, use `agent_chat_send` for each agent. "
        "Ordinary persona chat is chat-only for every role: investigations, verification, MCP calls, and multi-agent work "
        "stay in chat and never imply goal creation or create hidden durable work.\n"
        "- If an order is ambiguous or underspecified — an unclear target, a missing detail, or a routing choice with more "
        "than one plausible answer — use the `clarify` tool to ask before acting, rather than guessing. Pass the question, and "
        "when the answer is one of a few known options pass them as `choices` (up to 4) so they render as pickable rows. On "
        "this channel `clarify` does NOT block: it ends your turn with your question, and the answer arrives as their next "
        "message in this same conversation. This is the operator channel, not an autonomous goal run: here, asking beats "
        "guessing — but only about what is genuinely ambiguous, never for permission to carry out a clear order. Reach for it "
        "especially when you hold context the asker can't see (e.g. which of several same-role agents they mean).\n"
        "- When an agent you briefed replies with a clarifying question of their own, answer it by sending the choice back to "
        "them with `agent_chat_send` carrying the `clarify_token` that came inside their `clarify_request` — that lands your "
        "answer in the thread the question was asked in, so you don't have to get `session_id` right. Their reply's "
        "`session_id` still works too. Don't drop their question or answer it by guessing, and don't send the answer with "
        "neither (a send with no clarify_token and no session_id opens a NEW thread and they lose the question's context).\n"
        "- Teammates on your level are addressable by the `@personainst_*` handles in your Runtime Situation HUD. Threads are "
        "TASK-SCOPED with `agent_chat_send`: each new task you dispatch starts a fresh thread by default — just send, no flag. "
        "To continue an exchange you already started (their clarifying question, an in-task follow-up, a correction), pass the "
        "`session_id` that came back in their reply; the reply's `session_established` block tells you which thread you are in "
        "and which one it superseded. Optionally pass a short `title` to name the thread after the task. `new_session: false` "
        "continues that teammate's CURRENT thread — the most recently established one, which every fresh dispatch repoints, so "
        "it is not a stable per-pair home; to continue a SPECIFIC conversation, name its `session_id`. To recall "
        "earlier work with a teammate, search past sessions (`session_search`) or read a thread with `agent_chat_open` — do not "
        "keep an unrelated task thread alive just to preserve memory. `agent_chat_threads` lists your threads.\n"
        "- When a persona runs more than one instance on your level, a BARE persona id is ambiguous and the send is refused "
        "(`ambiguous_target`) with the candidate @personainst_* handles — address the exact instance you mean by its @handle.\n"
        "- Character and sprite-sheet authoring is a DELEGATION, not your own pipeline. When the ask is to make, fix, "
        "resume, add a state to, or install a character or an 8-way sprite sheet, and the charsheet authoring skill is "
        "NOT in your context this turn, do not drive `hermes harness characters` verbs yourself: dispatch the ask with "
        "`agent_chat_send` to the teammate on your level who carries the charsheet authoring skill. That persona holds "
        "the authoring contract preloaded on every turn and runs the generation spend on a cheaper model, so the same "
        "work costs a fraction of what it costs here — and driving it from this seat has already produced a 20-minute "
        "turn that shipped no pictures. Pick them by what they ARE, from the roster in your Runtime Situation HUD, and "
        "address the @personainst_* handle you find there; never an id you memorized from a previous run. Pass the "
        "operator's ask through intact along with any draft id already in play, and name in your acknowledgement who "
        "you handed it to. Their answer comes back as a background-dispatch delivery turn: relay it with every `MEDIA:` "
        "and `CHARSHEET-QA:` line reproduced verbatim, each alone on its own line, under the image-line carve-out "
        "below — those lines are the operator's only window onto the art, and a run that ends without them delivered "
        "nothing anyone can see. If nobody on your level carries that skill, say so and use `clarify` to ask whether to "
        "place an authoring agent, rather than quietly taking the pipeline. If the charsheet authoring skill IS in your "
        "context, none of this is aimed at you — you are that specialist; do the work.\n"
        "- Keep replies as clean teammate prose. Don't paste decision JSON, task scopes, acceptance criteria, handoff "
        "packets, or raw tool/tick scaffolding into the message — your tool calls are tracked separately in the trace lane.\n"
        "- One carve-out to that: image lines are content, not scaffolding. When you relay, quote, or summarize a "
        "teammate's reply that carries a MEDIA:<absolute image path> line, reproduce that line VERBATIM on a line of "
        "its own — never wrap it in backticks or a code fence, never fold it into a sentence, never retype or shorten "
        "the path. Same for a bare absolute screenshot path standing alone on its own line. WHY: a MEDIA: line alone "
        "on its own line is a DECLARATION, and the operator's console renders it as a titled image attachment card. "
        "Wrapping that line in backticks or a code fence un-declares it — the console never sees the prefix, and "
        "NOTHING renders. Retyping the path into a sentence, or dropping the prefix, is the quieter loss: the image "
        "still previews, but untitled, with the raw path left sitting in your prose, and it competes for the small "
        "per-message preview budget a declared line claims first. Either way the operator stops seeing the picture "
        "the way it was meant to be seen — so copy the line through exactly as it arrived, and put your provenance "
        "prose around it, never inside it."
    )


def _mission_chat_identity_prompt(persona: AgentPersona) -> str:
    """First-person identity block for the canonical Mission Control chat lane.

    This runtime-owned envelope names the selected Mission Control persona and
    makes self-relay impossible. It is distinct from the profile-owned SOUL
    overlay, which is resolved and inserted immediately after this block."""

    display = str(getattr(persona, "display_name", None) or getattr(persona, "id", "the agent")).strip()
    persona_id = str(getattr(persona, "id", "") or "").strip()
    id_clause = f" (Mission Control persona id: `{persona_id}`)" if persona_id else ""
    never_self = (
        f" Never use `agent_chat_send` to message `{persona_id}`: that persona is you — "
        "answer the operator directly instead of relaying to yourself."
        if persona_id
        else ""
    )
    return (
        f"You are {display}{id_clause}. You are already the persona speaking in this "
        "channel — the operator is talking to you right now, so respond directly in your own "
        f"voice.{never_self} Other runtime personas are teammates you may brief with "
        "`agent_chat_send`; you are not your own relay target."
    )


#: Fixed preamble prepended to the operator-selected workspace ``AGENTS.md``
#: body inside the surface message. Kept as one constant so the per-file
#: in-prompt attribution in ``prompt_observability`` can measure the workspace
#: part's contributed chars (preamble + body) WITHOUT drifting from the text
#: actually pasted here (T8, 2026-07-18).
#:
#: The second sentence is a scope statement, not a precedence engine. The
#: workspace file is arbitrary — whatever directory the operator aimed the
#: Mission Control picker at — so nothing on this side can vet its contents,
#: and an allowlist naming one repo's ``AGENTS.md`` would be answering the
#: wrong question. What IS knowable here is the boundary: a repo doc describes
#: the repo, and it never gets to redefine how this channel handles
#: confirmation. Stating that once, ahead of the body, is what keeps an
#: arbitrary workspace from contradicting ``_mission_chat_operative_rules()``
#: the way the launcher repo's AGENTS.md did on 2026-08-10.
MISSION_CHAT_WORKSPACE_AGENTS_PREAMBLE = (
    "Workspace instructions from the operator-selected AGENTS.md "
    "(apply these instructions to this turn). They describe the repository you "
    "are working in. They do NOT govern this operator channel: wherever they "
    "touch confirmation, permission, or go-ahead behavior, the Mission Control "
    "operator-chat rules above are authoritative and win.\n\n"
)


def _safe_read_soul_overlay(
    path_value: str | None, *, hermes_profile: str | None = None
) -> str | None:
    if not path_value:
        return None
    raw = Path(path_value)
    if raw.is_absolute() or not _is_safe_soul_overlay_path(raw):
        return None
    if hermes_profile:
        # A profile-backed persona owns its soul in ITS OWN profile home —
        # `profiles/<hermes_profile>/SOUL.md` is the single source (realm sync
        # already models soul_overlay as profile-home-relative). Repo prompts
        # stay as the shipped-default fallback. Deliberately NO operator-home
        # fallthrough here: on a miss, a bare `SOUL.md` must never resolve to
        # the OPERATOR profile's SOUL (the persona-identity-leak class).
        home = _persona_profile_home(hermes_profile)
        candidates = [
            *( [home / raw] if home is not None else [] ),
            Path(__file__).with_name("prompts") / raw.name,
        ]
    else:
        candidates = [
            Path(__file__).with_name("prompts") / raw.name,
            get_hermes_home() / raw,
        ]
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return None


def _mission_chat_soul_overlay(persona: AgentPersona) -> str | None:
    """Resolve the profile-owned SOUL text used by Mission Control chat.

    A profile-backed persona owns ``SOUL.md`` by convention.  An explicit safe
    relative ``soul_overlay_path`` still wins, while an unbound legacy persona
    keeps the old opt-in behavior.  Resolution remains profile-isolated through
    :func:`_safe_read_soul_overlay`, so a missing persona profile can never fall
    through to the operator's SOUL.
    """

    hermes_profile = getattr(persona, "hermes_profile", None)
    configured_path = getattr(persona, "soul_overlay_path", None)
    path_value = configured_path or ("SOUL.md" if hermes_profile else None)
    return _safe_read_soul_overlay(path_value, hermes_profile=hermes_profile)


def _persona_profile_home(name: str) -> Path | None:
    """Home directory of the named hermes profile, or None when unresolvable.

    Prefers the canonical CLI resolver; falls back to the standard
    ``<profiles root>/<name>`` layout beside the operator home. Kept as its own
    seam so tests can pin the home without touching global profile state."""

    try:
        from hermes_cli.profiles import get_profile_dir, normalize_profile_name, profile_exists

        normalized = normalize_profile_name(name)
        if profile_exists(normalized):
            return Path(get_profile_dir(normalized))
    except Exception:
        pass
    try:
        candidate = get_hermes_home().parent / name
        if candidate.exists():
            return candidate
    except OSError:
        pass
    return None


def _is_safe_soul_overlay_path(path: Path) -> bool:
    if path.suffix.lower() != ".md":
        return False
    unsafe_parts = {".env", "env", "auth", "credentials", "credential", "secrets", "secret", "tokens", "token", "config"}
    return not any(part.lower() in unsafe_parts or part.startswith(".") for part in path.parts)
