"""The ``@method`` registry — the program's reference implementation of rule 12.

``_METHODS`` (name → handler) and ``_METHOD_TIERS`` (name → tier) are written
ONLY by :func:`method`; the manifest and the dispatcher read them. Every verb
family module registers itself on import, and ``serve_rpc/__init__`` imports
the families in their original registration order so ``method_names()`` and
``manifest()`` are unchanged by the package split.
"""

from __future__ import annotations

from typing import Any, Callable

from agent_runtime.call_authorization import TIER_CONSOLE, TIERS

from agent_runtime.serve_rpc.protocol import RPC_CONTRACT_VERSION, RpcContext, err, ok

__layer__ = "lanes"

__all__ = [
    "_METHODS",
    "_METHOD_TIERS",
    "_ensure_discussion_methods",
    "_ensure_local_llama_methods",
    "manifest",
    "method",
    "method_names",
    "method_tier",
    "method_tiers",
]


_METHODS: dict[str, Callable[[Any, dict, "RpcContext"], dict]] = {}


#: name → the tier a caller must hold to run it. A PARALLEL registry rather than
#: a field on the handler, for the same reason ``_METHODS`` is a dict and not an
#: attribute sweep: the manifest and the gate both want the whole mapping, and a
#: thing you can iterate is a thing a test can assert is complete. Every entry is
#: written by :func:`method`, which has no default — see there.
#:
#: The classification rule is one line: **a level MUTATION is ``console``,
#: everything else is ``read``.** So the four ``runtime.office`` writes and both
#: ``runtime.agent`` verbs are ``console`` (the word their own docstrings and
#: canon 06 already used), while ``get`` / ``subscribe`` / ``unsubscribe`` are
#: ``read``.
#:
#: ``runtime.persona.prewarm`` is the one row worth arguing, and it is ``read``:
#: its contract is that it "writes no store state, emits no event and mints no
#: id", which is the same sentence that makes ``runtime.office.get`` a read. It
#: spends CPU, but spending CPU is a rate-limiting question and rate limiting is
#: not a tier — a viewer device that may not place an agent may certainly warm
#: the cache that makes its own reads fast.
#:
#: The gateway's two chat verbs (Stage 3) are the row that stretches the one-line
#: rule, and they are ``console``: a chat turn is not itself a level mutation,
#: but it RUNS AN AGENT WITH TOOLS, which can place, retire, write and dispatch.
#: A tier below ``console`` for them would be a door around ``console``. The full
#: argument, including why a new ``chat`` word would have refused every
#: already-paired console device, is on ``_runtime_chat_message``.
_METHOD_TIERS: dict[str, str] = {}


def method(name: str, tier: str):
    """Register a handler AND declare the tier a caller must hold to run it.

    ``tier`` is REQUIRED and has no default. A default is what turns a
    registration into a hole — either it defaults open, and a new verb ships
    unguarded the day someone forgets, or it defaults closed and a forgotten
    read verb breaks a client that was working. Requiring the word makes
    "which tier is this?" a question the author answers at the moment they know
    the answer, and makes a tierless method unrepresentable rather than merely
    untested.

    An unknown tier raises HERE, at import, rather than at the first call: the
    registry is built when the module loads, so a typo is a boot failure with a
    name in it instead of a verb that mysteriously refuses in the field.
    """

    if tier not in TIERS:
        raise ValueError(
            f"unknown tier {tier!r} for method {name!r}; expected one of {TIERS}"
        )

    def dec(fn):
        _METHODS[name] = fn
        _METHOD_TIERS[name] = tier
        return fn

    return dec


def _ensure_discussion_methods():
    if "runtime.discussion.capabilities" not in _METHODS:
        from ..discussions.rpc import register
        register(method, ok, err)


def _ensure_local_llama_methods():
    if "runtime.local_llama.status" not in _METHODS:
        from ..local_llama_adapter.rpc import register
        register(method, ok, err)


def method_names() -> list[str]:
    # Registration is lazy to keep imports one-directional and avoid eager
    # filesystem/process work on every client of the method manifest.
    _ensure_local_llama_methods()
    _ensure_discussion_methods()
    return sorted(_METHODS)


def method_tier(name: str) -> str:
    """The declared tier, or ``console`` for a name that has none.

    Unreachable through :func:`method`, which requires the word. It is the
    fallback for a registry mutated by some other path (a test monkeypatching
    ``_METHODS``, a future dynamic registration), and it fails CLOSED because the
    only safe answer to "nobody declared what this needs" is the strongest tier.
    """

    return _METHOD_TIERS.get(name, TIER_CONSOLE)


def method_tiers() -> dict[str, str]:
    """The whole mapping, sorted, for the manifest and for tests."""

    return {name: method_tier(name) for name in method_names()}


def manifest() -> dict[str, Any]:
    """What this runtime's method lane offers, for the greeting frames.

    Rides ``ready`` / ``hello_ok`` / the ``version`` reply. A client reads it
    once and knows both which methods exist and whether it understands their
    shape; a runtime that predates the lane carries no ``rpc`` block at all,
    which reads as "argv only" rather than as an error.

    ``tiers`` (Stage A1) says WHAT CREDENTIAL each method wants, so a connector
    can know before it tries. Additive by the set-plus-integer rule this
    module's header states and the D12 rollout already proved: it adds a key
    beside ``methods`` and changes no existing method's request or result shape,
    so ``RPC_CONTRACT_VERSION`` does not move. A client that ignores it is a
    client that keeps working — which is the point of shipping the declaration
    one stage ahead of the enforcement.

    It is deliberately a MAP and not a per-method sub-object. A tier is one
    string, and ``{"runtime.office.get": "read"}`` is the shape a client can
    index; wrapping each value in ``{"tier": …}`` would buy room for fields that
    do not exist and would make the addition of one look like a shape change.

    ``params`` (R-C8) says WHICH KEYS a method honours, for the same reason and
    under the same additive rule. The C5 field run is why: a console send to the
    Mac was refused before a byte left the launcher, because the launcher's
    lowering could see that ``runtime.chat.message`` EXISTS and not that it
    ignores ``workspace_name``, and a client that cannot tell "ignored" from
    "honoured" must assume the worst about every key it is not certain of. This
    lane ignores unknown params by contract — a client cannot be refused for a
    key a runtime has never heard of — so the only way to make that safe is to
    publish what is heard. It covers the chat verbs and only those: they are the
    ones whose surface an operator types into, and a block that claimed to be
    exhaustive over twenty-six methods would be a promise this function cannot
    keep. A client reading a manifest with NO ``params`` block reads it as "the
    runtime that predates R-C8", not as "no params" — the same way a runtime
    with no ``rpc`` block at all reads as "argv only".

    The lists are derived from ``chat_turn``'s own tuples, which its normalisers
    read, so the advertisement cannot drift from the code that honours it; a
    test walks a recording mapping through each normaliser and asserts the two
    agree.
    """

    from ..chat_turn import CHAT_TURN_METHOD_PARAMS

    return {
        "contract": RPC_CONTRACT_VERSION,
        "methods": method_names(),
        "tiers": method_tiers(),
        "params": {
            name: list(keys) for name, keys in sorted(CHAT_TURN_METHOD_PARAMS.items())
        },
    }
