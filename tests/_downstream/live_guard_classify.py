"""Fork half of the ``_live_system_guard`` argv classifier in ``tests/conftest.py``.

A multi-line script's shell COMMENTS are not commands: prose like
"Hermes loads $HERMES_HOME/.env" followed anywhere later by the word "gateway"
used to read as ``hermes ... gateway`` (fork-hygiene 2026-09-24,
docker/stage2-hook.sh's keygen block). Kept here so the upstream conftest
carries a one-line call rather than the helper (the ``[up-fp]`` ratchet).

The backend-spawn arm lives here too (lane FOOTPRINT-DROP 2026-09-27): the fixture in
``tests/_fixtures/live_system_guard.py`` calls :func:`refuse_backend_spawn` once, from
the ``_check_subprocess_cmd`` chokepoint every spawn primitive funnels through.
"""

from __future__ import annotations

import ast
import re
import shlex


def strip_shell_comments(script: str) -> str:
    """*script* with each ``#`` comment removed, the way sh reads one: a ``#``
    that begins a word and is outside quotes runs to end of line."""
    kept = []
    for line in script.splitlines():
        quote = None
        cut = len(line)
        for index, char in enumerate(line):
            if quote:
                if char == quote:
                    quote = None
            elif char in ("'", '"'):
                quote = char
            elif char == "#" and (index == 0 or line[index - 1].isspace()):
                cut = index
                break
        kept.append(line[:cut])
    return "\n".join(kept)


def script_words(token: str) -> list[str]:
    """Whitespace words of one argv token; a script token (one with a newline)
    loses its comments first, a single-line argv token is split as it was."""
    if "\n" in token:
        token = strip_shell_comments(token)
    return token.split()


# ── Backend-spawn arm (ML-14 / B20(i)) ─────────────────────────────
#
# The fixture's other arms stop a test SIGNALLING or SERVICE-MUTATING the operator's
# live backend. They do not stop a test STARTING one, and that hole was
# load-bearing: ``hermes gateway run`` / ``hermes serve`` /
# ``hermes dashboard`` (and the ``python -m hermes_cli.main …`` spelling the
# desktop app uses) each boot a real backend against whatever root the
# environment resolves to, publish the machine-global root anchor, bind a
# port, and outlive the test — a live process the suite never asked for and
# nothing here would ever notice. The launcher runs against that same live
# runtime on this workstation, so the blast radius is another program's
# state, not just a slow test.
#
# ONE CHOKEPOINT: this classifier lives beside the systemctl / process-killer
# / ``hermes update`` arms, in the same ``_check_subprocess_cmd`` that every
# spawn primitive (run/Popen/call/check_*/getoutput/os.system/os.popen/
# pty.spawn/asyncio.create_subprocess_*) already funnels through. A
# directory-local fixture would have been a second fence over a subset of
# the same primitives.
#
# It scans EVERY non-flag token after the entry point rather than only the
# first, because ``hermes harness serve`` and ``hermes --profile x gateway
# run`` both put the subcommand past position 1 and flag arity is unknowable
# here. That deliberately over-refuses (a hermes invocation carrying a bare
# positional spelled ``gateway``/``serve``/``dashboard``): the cost of a
# false refusal is a red test and a one-line marker, the cost of a false
# pass is a live backend on the operator's machine.
_BACKEND_SUBCOMMANDS = ("gateway", "serve", "dashboard")
_HERMES_ENTRYPOINT_BASENAMES = ("hermes", "hermes.exe")
_PYTHON_BASENAME_RE = re.compile(r"^pythonw?(\d+(\.\d+)*)?(\.exe)?$")


def _without_python_c_argv(raw: list) -> list:
    """*raw* cut after CODE / SCRIPT when it is ``python [opts] -c CODE ARGS...`` or
    ``python [opts] SCRIPT ARGS...``.

    ARGS are only the program's ``sys.argv``, so a ``-m hermes_cli.main serve`` tail
    there is inert data (the live venv-holder / desktop-lifecycle E2Es spawn exactly
    that sleeper, as ``-c`` or as a script, for psutil to classify) and never an
    entry point. Keep CODE / SCRIPT (it may itself be the entry point: a SCRIPT that
    IS ``hermes_cli/main.py`` or a ``hermes`` launcher keeps its ARGS), drop ARGS.
    ``-m MODULE ARGS`` is never cut. Mirrored in
    ``tests/hermes_cli/_gateway_fence.py::_without_python_c_argv``.
    """
    if not raw or not _PYTHON_BASENAME_RE.match(
        str(raw[0]).replace("\\", "/").rsplit("/", 1)[-1].lower()
    ):
        return raw
    index = 1
    while index < len(raw):
        token = str(raw[index])
        if token == "-c":
            return raw[: index + 2]
        if token in ("-X", "-W"):
            index += 2
            continue
        if token == "-m":
            return raw
        if not token.startswith("-"):
            # SCRIPT: cut its ARGS unless the script itself is a hermes entry point.
            script = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if script in ("hermes", "hermes.exe") or token.replace("\\", "/").lower().endswith("hermes_cli/main.py"):
                return raw
            return raw[: index + 1]
        index += 1
    return raw


# Identifiers through which ``python -c CODE`` could start a process or reach a hermes
# backend in-process. The fence does not follow the child, so CODE is scanned here.
_SPAWN_CAPABLE_NAMES = frozenset({
    "subprocess", "os", "pty", "asyncio", "multiprocessing", "runpy", "importlib",
    "exec", "eval", "compile", "__import__", "ctypes", "sys",
})
_BACKEND_NAME_PARTS = ("hermes", "gateway", "serve", "dashboard")


def _no_names(_node) -> tuple:
    return ()


def _alias_names(node) -> list:
    return [*node.name.split("."), *([node.asname] if node.asname else [])]


# The identifiers each AST node kind contributes: a name, an attribute, an import
# alias, an ``import from`` module path. Every other node contributes nothing.
_NODE_NAMES = {
    ast.Name: lambda node: (node.id,),
    ast.Attribute: lambda node: (node.attr,),
    ast.alias: _alias_names,
    ast.ImportFrom: lambda node: node.module.split(".") if node.module else (),
}


def _python_c_code_is_inert(code: str) -> bool:
    """True when CODE parses and names nothing that could spawn or boot a backend.

    Only then are its string literals data rather than a command line: the words
    ``hermes gateway`` inside a literal the code merely compares cannot start one.
    Anything else (unparseable, or any spawn-capable or backend-named identifier,
    import or attribute) keeps the conservative word scan.
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    names = set()
    for node in ast.walk(tree):
        names.update(_NODE_NAMES.get(type(node), _no_names)(node))
    lowered = {name.lower() for name in names}
    if lowered & _SPAWN_CAPABLE_NAMES:
        return False
    return not any(part in name for name in lowered for part in _BACKEND_NAME_PARTS)


def _without_inert_python_c_code(raw: list) -> list:
    """*raw* without CODE when it is ``python [opts] -c CODE`` and CODE is inert."""
    if len(raw) >= 3 and raw[-2] == "-c" and _PYTHON_BASENAME_RE.match(
        str(raw[0]).replace("\\", "/").rsplit("/", 1)[-1].lower()
    ) and _python_c_code_is_inert(str(raw[-1])):
        return raw[:-1]
    return raw


def _cmd_tokens(cmd, cmd_to_string) -> list:
    # argv lists are tokenized by construction; only strings need shlex,
    # which on Windows would otherwise eat the backslashes in a path.
    if isinstance(cmd, (list, tuple)):
        raw = [str(token) for token in cmd]
    else:
        cmd_str = cmd_to_string(cmd)
        try:
            raw = shlex.split(cmd_str)
        except ValueError:
            raw = cmd_str.split()
    raw = _without_inert_python_c_code(_without_python_c_argv(raw))
    # A wrapper's argument is itself a whole command: ``["bash", "-c",
    # "hermes gateway run"]`` arrives as THREE elements, the last of which
    # is the command. Split on whitespace (not shlex — it would eat the
    # backslashes in a Windows path) so the entry point inside it is
    # reachable. Splitting cannot invent an entry point: a path containing
    # spaces still ends in its own basename.
    tokens = []
    for token in raw:
        tokens.extend(script_words(token))
    return tokens


def backend_spawn_subcommand(cmd, cmd_to_string):
    """Which backend subcommand this argv would START, or ``None``."""
    tokens = _cmd_tokens(cmd, cmd_to_string)
    entry = None
    for index, token in enumerate(tokens):
        normalized = str(token).replace("\\", "/").lower()
        if normalized.rsplit("/", 1)[-1] in _HERMES_ENTRYPOINT_BASENAMES:
            entry = index
            break
        if normalized == "hermes_cli.main" or normalized.endswith(
            "hermes_cli/main.py"
        ):
            entry = index
            break
    if entry is None:
        return None
    for token in tokens[entry + 1:]:
        text = str(token)
        if text.startswith("-"):
            continue
        if text.lower() in _BACKEND_SUBCOMMANDS:
            return text.lower()
    return None


def refuse_backend_spawn(name, cmd, cmd_to_string, lookalike_ok) -> None:
    """Raise when *cmd* would START a hermes backend; a lookalike-marked test may start only a gateway."""
    backend = backend_spawn_subcommand(cmd, cmd_to_string)
    # The existing marker permits only a test-owned gateway lookalike.
    # Other backend entry points remain forbidden even in marked tests.
    if backend is not None and not (backend == "gateway" and lookalike_ok):
        raise RuntimeError(
            f"tests/conftest.py live-system guard: blocked "
            f"subprocess.{name}({cmd!r}) — this command would START a "
            f"hermes backend (`{backend}`). A real backend boot resolves "
            "its own runtime root, publishes the machine-global root "
            "anchor, binds a port and outlives the test; on this "
            "workstation the launcher runs against that same live runtime. "
            "Drive the code in-process (build the parser, call the handler, "
            "fake the transport) instead of spawning the CLI, or mark with "
            "@pytest.mark.live_system_guard_bypass if the claim genuinely "
            "needs a real child — and say in a comment WHAT it spawns and "
            "how the child's root is sandboxed."
        )
