"""The six ``agent_chat_*`` tool schemas and the relay's two limits (a TABLE module: exempt from the 100-line floor)."""

from __future__ import annotations



__layer__ = "models"


#: The relay's own reply bound — the same number as ``dispatch_store.REPLY_LIMIT``
#: and ``dispatch_delivery.REPLY_LIMIT`` under a private spelling, and fenced
#: equal to both by ``tests/agent_runtime/test_mirrored_constant_fences.py``.
_REPLY_LIMIT = 8000
_MESSAGE_LIMIT = 12000

AGENT_CHAT_SEND_SCHEMA = {
    "name": "agent_chat_send",
    "description": (
        "Send a conversational message to ANOTHER Harness persona (persona id e.g. neko_supervisor/dev/qa, or a @personainst_* handle for a specific instance; display names refused). Each new task you dispatch starts a FRESH thread by default; to continue an exchange (an in-task follow-up) pass back the session_id their reply returned. Answering their clarifying question: pass back the clarify_token from their clarify_request and your answer lands in that question's thread. new_session=false continues the target's CURRENT default thread (the most recent one) instead. This is conversational only and does not create tracked work."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "persona_id": {
                "type": "string",
                "description": (
                    "Target persona id, e.g. 'neko_supervisor' (reaches the canonical primary "
                    "instance). A personainst_* handle is also accepted and targets THAT specific "
                    "instance — use it to reach a non-primary instance when a persona runs several. "
                    "To reach an agent on a PAIRED INSTALL on another machine, qualify the target "
                    "with that install: '@workstation/dev'. Cross-install sends need wait=false. "
                    "Anything without an @install/ prefix is on this install."
                ),
            },
            "message": {
                "type": "string",
                "description": (
                    "The message to deliver, written TO the target agent: the ask, relevant context, "
                    "and what they should come back with. Include who the request originates from."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Continue THIS exact thread — pass back the session_id a previous reply "
                    "returned to answer their clarifying question or send an in-task follow-up. "
                    "Omit when dispatching a new task. Cannot be combined with new_session=true."
                ),
            },
            "clarify_token": {
                "type": "string",
                "description": (
                    "Answering a teammate's clarifying question: pass back the clarify_token that "
                    "came inside their clarify_request. It puts your answer in the thread the "
                    "question was asked in, so you do not have to get session_id right. Omit for "
                    "anything else. Cannot be combined with new_session=true."
                ),
            },
            "new_session": {
                "type": "boolean",
                "description": (
                    "Omit this: a new task dispatch already gets its own fresh thread. Pass false to "
                    "continue the target's CURRENT default thread instead — that is the most "
                    "recently established one, not a stable per-pair thread, so name the session_id "
                    "when you mean a SPECIFIC conversation. Pass true to force a fresh thread where "
                    "the default would not. Cannot be combined with session_id."
                ),
            },
            "title": {
                "type": "string",
                "description": (
                    "Optional short name for the thread this dispatch opens (e.g. 'Flaky login "
                    "test triage'). Defaults to the opening words of your message. Ignored when "
                    "you continue an existing thread."
                ),
            },
            # No schema ``default``, for the same reason ``new_session`` has
            # none: a provider that materialises schema defaults would send 240
            # on every call, and a wait=false dispatch would then silently be
            # capped at a conversational window instead of the 30-minute
            # background budget. Absent must stay distinguishable from stated.
            "max_seconds": {
                "type": "number",
                "description": (
                    "Wall budget for the target's reply turn. Omit unless you need a specific "
                    "window: waiting sends default to 240s, and a wait=false dispatch defaults to "
                    "the background budget (30 min)."
                ),
            },
            "wait": {
                "type": "boolean",
                "description": (
                    "Pass false to DISPATCH AND KEEP WORKING: the call returns a dispatch_id "
                    "immediately, their turn runs in the background on its own longer budget "
                    "(default 30 min), and their answer is delivered to you as a new message in "
                    "this conversation once you are idle. Use it for anything that takes real time "
                    "— test suites, builds, long reviews — instead of blocking your turn on it. "
                    "Default true: you wait for the reply inline, exactly as before. Check on "
                    "in-flight work with agent_chat_dispatches."
                ),
            },
            "notify_operator": {
                "type": "boolean",
                "description": (
                    "Only meaningful with wait=false. Pass true when the operator is waiting on "
                    "this result: the delivered turn will instruct you to tell them what came back. "
                    "Default false."
                ),
            },
        },
        "required": ["persona_id", "message"],
    },
}


AGENT_CHAT_DISPATCHES_SCHEMA = {
    "name": "agent_chat_dispatches",
    "description": (
        "List the background dispatches YOU sent with agent_chat_send(wait=false): who they went to, what you asked, whether they are still running or finished, and whether their answer has been delivered back to you yet. Read-only, bounded. Use it to check on long-running work without pestering the teammate. Disambiguator: this lists YOUR background dispatches; agent_chat_threads lists your threads; agent_chat_open reads one."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many of your most recent dispatches to return. Default 10, clamped to 1..100.",
                "default": 10,
            },
            "state": {
                "type": "string",
                "description": (
                    "Optional filter: 'running' for only what is still in flight, 'done' for only "
                    "what has finished. Omit for both."
                ),
            },
        },
        "required": [],
    },
}


# --------------------------------------------------------------------------- #
# Read-only companions: list your threads / review a thread before continuing. #
#                                                                             #
# Both derive from EXISTING stores (persona-instance roster + persona-chat     #
# history / SessionDB read paths) — no new store, no new index, no mint. They  #
# resolve a target's DEFAULT thread through the SAME chokepoint the send lane  #
# uses (``resolve_default_chat_session_id_for_instance``), so what they list   #
# is exactly the thread an omitted-session ``agent_chat_send`` would continue. #
# --------------------------------------------------------------------------- #


AGENT_CHAT_THREADS_SCHEMA = {
    "name": "agent_chat_threads",
    "description": (
        "List your agent-to-agent chat threads with teammates on your level: persona id, display name, @personainst_* handle, and the default thread's session/title/activity when one exists. Read-only. Disambiguator: lists threads; agent_chat_open reads one, agent_chat_send sends."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "persona_id": {
                "type": "string",
                "description": (
                    "Optional filter: a single persona id or personainst_* handle to list just that "
                    "teammate's thread. Omit to list your addressable teammates on this level — each "
                    "persona's deliberate placement, with the plumbing canonical row shown only when "
                    "the persona has no placement on your level. Prefix with @install/ (e.g. "
                    "'@mac/dev') to list a teammate on another paired install instead; "
                    "agent_chat_installs names the installs you can reach."
                ),
            },
        },
        "required": [],
    },
}


AGENT_CHAT_OPEN_SCHEMA = {
    "name": "agent_chat_open",
    "description": (
        "Review the recent message tail of a thread with ONE teammate (persona id, or a @personainst_* handle for a specific instance) — 'what did we last say to each other?' before you continue it or inspect what a dispatched task actually said. Reviews their current default thread, or the session_id you name. Read-only; never creates a session. Disambiguator: agent_chat_open READS a thread; agent_chat_send replies; agent_chat_threads lists your threads."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "persona_id": {
                "type": "string",
                "description": (
                    "Target teammate: a persona id (e.g. 'dev' — reaches the persona's deliberate "
                    "placement on your level, or the canonical channel when it has none) or a "
                    "personainst_* handle (reaches THAT specific instance). Display names are not "
                    "accepted."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional specific thread to review. Omit to review the default thread with the "
                    "target. Must belong to the target's chat lane; otherwise the read is refused. "
                    "REQUIRED when persona_id names another install (@mac/dev): there is no shared "
                    "default thread across installs — pass the session_id your dispatch delivery "
                    "reported as 'Their thread'."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "How many of the newest messages to return. Default 20, clamped to 1..40.",
                "default": 20,
            },
        },
        "required": ["persona_id"],
    },
}


AGENT_CHAT_INSTALLS_SCHEMA = {
    "name": "agent_chat_installs",
    "description": (
        "List the other INSTALLS (machines) paired with this one — which are reachable right now, and optionally who is on one of them. Read-only: it never pairs, never mints and never sends. Use it before addressing @install/persona so you name a machine that is actually reachable and a teammate that is actually there. Disambiguator: agent_chat_installs lists MACHINES; agent_chat_threads lists teammates on this machine (or, with @install/, on one of theirs)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "install": {
                "type": "string",
                "description": (
                    "Optional: an install's name or id (from a previous call) to fetch THAT "
                    "install's roster of addressable agents. Omit to list the paired installs "
                    "themselves without contacting any of them."
                ),
            },
        },
        "required": [],
    },
}


AGENT_CHAT_LOG_PATH_SCHEMA = {
    "name": "agent_chat_log_path",
    "description": (
        "Get the FILE PATH of a teammate thread's transcript log so you can grep/glob/tail it with your own file tools — use this when 40 messages is not enough, when you need to search a long thread for something specific, or when you want to watch what a teammate is doing while they are still working. The file is append-only JSONL and redaction-safe. It holds the thread's materialized history, and it KEEPS GROWING: appended as they happen are operator/relay messages, mid-turn steers, each turn's final reply, and compact tool start/finish lines (so you can see what they are doing right now). Not appended live: the runtime's non-final rows — the intermediate assistant messages between tool calls. Those are in the materialized history but will not show up in a live tail, so do not read their absence as 'it never happened'. Disambiguator: agent_chat_log_path gives you the thread as a greppable file; agent_chat_open is the quick bounded 40-message tail; agent_chat_threads lists your threads; agent_chat_send sends. Read-only: it never creates a chat session and never sends anything."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "persona_id": {
                "type": "string",
                "description": (
                    "Target teammate: a persona id (e.g. 'dev') or a personainst_* handle for a "
                    "specific instance. Display names are not accepted."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional specific thread. Omit for the default thread with the target. Must "
                    "belong to that teammate's chat lane; otherwise the request is refused."
                ),
            },
            "all_threads": {
                "type": "boolean",
                "description": (
                    "Pass true to get a path for EVERY thread you share with this teammate instead "
                    "of just the current default one. Useful when a task was dispatched into its own "
                    "thread and you do not know which."
                ),
                "default": False,
            },
        },
        "required": ["persona_id"],
    },
}
