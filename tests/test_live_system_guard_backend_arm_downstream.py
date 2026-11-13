"""The live-system guard's backend-spawn arm reads ``python SCRIPT ARGS`` by contract.

``python [opts] SCRIPT ARGS...`` runs SCRIPT; ARGS are its ``sys.argv``. Upstream's
desktop-lifecycle E2Es spawn a sleeper SCRIPT whose argv tail is
``-m hermes_cli.main serve`` for psutil to classify - inert data, not a backend
start (2026-09-25 merge). The same argv with the entry point as the program still
refuses. Every spawn here names a script that does not exist, so nothing that
starts can be a backend (python exits on "can't open file").
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests._downstream.live_guard_classify import backend_spawn_subcommand

_SERVE_TAIL = ["-m", "hermes_cli.main", "serve"]


def test_a_sleeper_script_with_a_serve_tail_is_not_a_backend_start(tmp_path):
    missing_script = tmp_path / "sleeper.py"  # never created
    proc = subprocess.Popen([sys.executable, str(missing_script), *_SERVE_TAIL],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert proc.wait(timeout=30) != 0  # the interpreter refused the missing script


@pytest.mark.parametrize("argv", [
    lambda tmp: [sys.executable, *_SERVE_TAIL],
    lambda tmp: [sys.executable, str(tmp / "hermes_cli" / "main.py"), "serve"],
    lambda tmp: [str(tmp / "bin" / "hermes"), "serve"],
], ids=["python-m", "main-py-script", "hermes-launcher"])
def test_a_real_entry_point_with_serve_is_still_refused(tmp_path, argv):
    with pytest.raises(RuntimeError, match="would START a hermes backend"):
        subprocess.Popen(argv(tmp_path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_python_c_code_that_only_compares_backend_words_is_not_a_backend_start():
    # v0.21.6's approval-scan tests feed "stop/restart hermes gateway" prose to a
    # detector inside ``python -c``: a literal the code compares, not a command.
    code = 'cases = {"hermes gateway restart": "stop/restart hermes gateway (kills agents)"}\nassert cases'
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# v0.21.6's cron lifecycle-guard scan tests BUILD ``"hermes " + ... + "gateway stop"`` in
# ``python -c`` and feed it to a detector whose own name carries "gateway". A backend word on
# a called attribute is not a load; only an import path can boot one in-process. Classified
# directly (the child would need the repo on its path): no spawn is the claim.
@pytest.mark.parametrize("code", [
    'from cron import lifecycle_guard as guard\n'
    'command = "hermes " + "--quiet " * 58 + "-p default" + " gateway stop"\n'
    'assert guard.contains_gateway_lifecycle_command(command)',
    'import cron.lifecycle_guard\n'
    'assert not cron.lifecycle_guard.contains_gateway_lifecycle_command("hermes serve")',
], ids=["from-import-alias", "dotted-import"])
def test_python_c_code_that_only_builds_backend_words_for_a_detector_is_not_a_backend_start(code):
    assert backend_spawn_subcommand([sys.executable, "-c", code], str) is None


# The word scan matches bare words (prose, comments); these carry the same bare words
# as the inert case above, beside an identifier that could spawn, so they must still
# refuse. Cases 6-8 quote the entry point the way code spells a command
# (``run("hermes``, ``['hermes',``): the scan splits quotes and call punctuation off a word.
# The last two build the words as data, beside a backend IMPORT or a spawn-capable name.
@pytest.mark.parametrize("code", [
    'import subprocess\nx = 1  # then hermes gateway run',
    'import os\nnote = "stop/restart hermes gateway now"',
    'from hermes_cli.main import main\nnote = "stop/restart hermes gateway now"',
    '__import__("json")\nnote = "stop/restart hermes gateway now"',
    'note = "stop/restart hermes gateway now" +',  # unparseable
    'import subprocess; subprocess.run("hermes gateway run")',
    "import subprocess; subprocess.run(['hermes', 'serve'])",
    'import os; os.system("hermes dashboard")',
    'import gateway.run as runner\ncommand = "hermes " + "gateway run"',
    'from cron import lifecycle_guard\nimport subprocess\ncommand = "hermes " + "gateway run"',
], ids=["subprocess", "os", "hermes-cli-in-process", "dunder-import", "unparseable",
        "quoted-string", "quoted-argv", "quoted-os-system", "backend-import-builds-words",
        "detector-import-beside-spawn"])
def test_python_c_code_that_could_spawn_keeps_the_conservative_scan(code):
    with pytest.raises(RuntimeError, match="live-system guard: blocked"):
        subprocess.run([sys.executable, "-c", code], timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


# ``executable=`` names the program the OS runs; argv[0] is only the child's displayed name.
# The browse-drift legacy-gateway sleeper is ``["hermes", "-c", CODE, <db>, "gateway", "run"]``
# under ``executable=sys.executable``: a Python ``-c`` child dressed as a gateway for a psutil
# holder scan, never a backend start (land/w1029c, RT-MAIN-REDS-SQLITE-OPEN-FAMILY).
_DRESSED_SLEEPER = ["hermes", "-c", "import time\ntime.sleep(0)\n", "state.db", "gateway", "run"]


def test_an_interpreter_named_hermes_by_argv0_is_not_a_backend_start():
    assert backend_spawn_subcommand(_DRESSED_SLEEPER, str, {"executable": sys.executable}) is None
    proc = subprocess.Popen(_DRESSED_SLEEPER, executable=sys.executable,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert proc.wait(timeout=30) == 0


def test_the_same_argv_with_no_executable_is_still_refused():
    # Positive control: the bytes above, minus ``executable=``, run a real ``hermes`` launcher.
    assert backend_spawn_subcommand(_DRESSED_SLEEPER, str) == "gateway"
    with pytest.raises(RuntimeError, match="would START a hermes backend"):
        subprocess.Popen(_DRESSED_SLEEPER, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_an_executable_that_is_the_hermes_launcher_is_refused_whatever_argv0_says(tmp_path):
    argv = ["python", "gateway", "run"]
    assert backend_spawn_subcommand(argv, str, {"executable": str(tmp_path / "bin" / "hermes")}) == "gateway"


# ``hermes update``'s import-health probe carries ``sys.argv = ['hermes', 'update']`` and the
# first-party roots (``'gateway'`` ...) as data inside ``runtime_command``'s ``exec`` wrapper:
# an import check, never a backend (FH-UPDATE-TESTS-RED-ON-LINUX-MAIN). The marker alone
# does not exempt code that calls anything outside the probe's own calls.
def _update_import_probe_argv(tmp_path, extra=""):
    from hermes_cli._launchers import runtime_command
    code = ("import importlib, json, sys\nsys.argv = ['hermes', 'update']\n"
            "for name in ('hermes_cli.main',):\n    importlib.import_module(name)\n"
            f"roots = ('gateway', 'tui_gateway')\n{extra}"
            "sys.stdout.write('\\n__HERMES_IMPORT_HEALTH_abc__' + json.dumps([]))\n")
    return runtime_command(tmp_path, code=code)


def test_the_update_import_probe_is_not_a_backend_start(tmp_path):
    assert backend_spawn_subcommand(_update_import_probe_argv(tmp_path), str) is None


def test_a_marked_probe_that_could_spawn_keeps_the_conservative_scan(tmp_path):
    argv = _update_import_probe_argv(tmp_path, "__import__('subprocess').run(['hermes', 'gateway', 'run'])\n")
    assert backend_spawn_subcommand(argv, str) == "gateway"


# FH-HERMES-CLI-GATEWAY-UPDATE-REDS-REMAINDER: a grep-family quoted PATTERN is data. Mutation: return
# ``script`` unchanged from ``drop_grep_patterns`` -> the first test is red (`gateway`).
_HINT_BLOCK = ('OWED_HINT=hint\n'
               '    if [ -n "$GW_REASONS" ] && ! printf \'%s\\n\' "$GW_REASONS" | grep -q "hermes gateway restart"; then\n'
               '      OWED_HINT=""\n    fi\nprintf %s "$OWED_HINT"')


def test_a_quoted_grep_pattern_in_a_script_is_not_a_backend_start():
    assert backend_spawn_subcommand(["bash", "-c", _HINT_BLOCK], str) is None
    assert backend_spawn_subcommand(["bash", "-c", "grep -qE 'hermes (gateway|serve)' log"], str) is None


@pytest.mark.parametrize("script", [
    'grep -q x\nhermes gateway run\n',                          # a second command after the grep
    'grep "x" "$(hermes gateway run)"\n',                       # an expansion in a later word
    "grep 'x; hermes gateway run'\n",                           # a span with a command boundary
    'grep "$(hermes gateway run)"\n',                           # an expansion in the pattern itself
    'grep "x" && "hermes" gateway run',                         # a quoted entry point after a boundary
    "f() { hermes gateway run; }\ngrep -q 'hermes gateway' log && f",
])
def test_a_script_whose_grep_hides_nothing_still_refuses_the_real_start(script):
    assert backend_spawn_subcommand(["bash", "-c", script], str) == "gateway"


# FH-LIVE-GUARD-PATH-READ-AS-SPAWN: upstream's spawn-intent matcher answers ``run`` for any argv
# holding ``gateway/run.py``. A program that reads the path as data runs; one that executes it
# (argv[0], or a Python interpreter's SCRIPT) is still refused. Mutation: drop the guard's
# ``gateway_run_path_is_only_data`` clause -> the git pathspec spawn is blocked, red.
def test_a_git_pathspec_naming_gateway_run_py_is_not_a_gateway_spawn():
    subprocess.run(["git", "ls-files", "--", "gateway/run.py"], check=True, timeout=30,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.mark.parametrize("argv", [
    lambda tmp: [sys.executable, str(tmp / "gateway" / "run.py")],
    lambda tmp: ["env", "HERMES_X=1", sys.executable, "-X", "utf8", str(tmp / "gateway" / "run.py")],
    lambda tmp: [str(tmp / "gateway" / "run.py"), "--replace"],
], ids=["python-script", "env-wrapped-python-with-options", "script-as-program"])
def test_a_gateway_run_py_the_program_executes_is_still_refused(tmp_path, argv):
    with pytest.raises(RuntimeError, match="spawn a REAL hermes gateway"):
        subprocess.Popen(argv(tmp_path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# FH-GUARD-PATH-WORDS-READ-AS-SPAWN: an argv element with spaces that names an existing file is a path
# operand. Split into words, ``…/0012 — The hermes half of ….md`` + ``…/Touching serve and boot.md`` read as
# ``hermes serve`` and blocked the line-endings gate's ``git ls-files --eol`` over the brain's notes.
def test_a_git_pathspec_with_backend_words_in_its_name_is_not_a_spawn(tmp_path):
    for name in ("The hermes half of it.md", "Touching serve and boot.md"):
        (tmp_path / name).write_text("", encoding="utf-8")
    argv = ["git", "ls-files", "--eol", "--", "The hermes half of it.md", "Touching serve and boot.md"]
    assert backend_spawn_subcommand(argv, str, {"cwd": tmp_path}) is None


def test_a_wrapper_command_string_that_names_no_file_is_still_split(tmp_path):
    assert backend_spawn_subcommand(["bash", "-c", "hermes serve"], str, {"cwd": tmp_path}) == "serve"


# v0.23.1's ssh spawn test syntax-checks the remote ``hermes serve`` script with ``sh -n -c``:
# noexec reads the script and runs nothing. An interactive shell ignores ``-n``.
def test_a_parse_only_shell_is_not_a_backend_start():
    assert backend_spawn_subcommand(["sh", "-n", "-c", "hermes serve"], str) is None
    assert backend_spawn_subcommand(["/bin/dash", "-nc", "hermes serve"], str) is None
    assert backend_spawn_subcommand(["sh", "-c", "hermes serve"], str) == "serve"
    assert backend_spawn_subcommand(["bash", "-i", "-n", "-c", "hermes serve"], str) == "serve"
    assert backend_spawn_subcommand("sh -n -c 'hermes serve'", str) == "serve"


# ``hermes gateway attach`` (v0.23.1) only discovers the owner unless ``--start`` / ``--recover``.
def test_gateway_attach_without_start_is_not_a_backend_start():
    attach = [sys.executable, "-m", "hermes_cli.main", "gateway", "attach", "--json"]
    assert backend_spawn_subcommand(attach, str) is None
    assert backend_spawn_subcommand([*attach, "--start"], str) == "gateway"
    assert backend_spawn_subcommand([*attach, "--recover"], str) == "gateway"
    assert backend_spawn_subcommand(["hermes", "gateway", "run"], str) == "gateway"
    assert backend_spawn_subcommand(["hermes", "gateway"], str) == "gateway"


# FH-MAIN-RED-COMMAND-DISCOVERY-SERVE-GUARD: upstream's discovery test boots a dedicated
# ``python -m hermes_cli.main serve --isolated`` with HERMES_HOME and HOME both re-homed to its
# tmp dir; the guard lets exactly that through. The interpreter here does not exist, so a case
# the guard admits raises FileNotFoundError at exec, and nothing can boot. Mutation: drop the
# ``--isolated`` test in ``is_isolated_serve_module`` (tests/_downstream/live_guard_classify.py)
# -> the ``unisolated`` case is admitted, red; drop the serve early return in
# ``refuse_backend_spawn`` -> the isolated case is refused, red.
_ISOLATED_SERVE = ["-m", "hermes_cli.main", "serve", "--host", "127.0.0.1", "--port", "0", "--isolated"]


def _account_home():
    import pwd
    return pwd.getpwuid(os.getuid()).pw_dir


def _rehomed(tmp_path, **overrides):
    env = {"PATH": os.environ.get("PATH", ""), "HERMES_HOME": str(tmp_path / "state"),
           "HOME": str(tmp_path / "user")}
    env.update(overrides)
    return env


@pytest.mark.platforms("linux")
def test_an_isolated_serve_on_a_sandboxed_home_reaches_the_exec(tmp_path):
    with pytest.raises(FileNotFoundError):
        subprocess.Popen([str(tmp_path / "python3"), *_ISOLATED_SERVE], env=_rehomed(tmp_path),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.mark.platforms("linux")
@pytest.mark.parametrize("argv, env", [
    (lambda tmp: _ISOLATED_SERVE, lambda tmp: _rehomed(tmp, HOME=_account_home())),
    (lambda tmp: _ISOLATED_SERVE, lambda tmp: _rehomed(tmp, HERMES_HOME=os.path.join(_account_home(), ".hermes"))),
    (lambda tmp: _ISOLATED_SERVE, lambda tmp: {k: v for k, v in _rehomed(tmp).items() if k != "HOME"}),
    (lambda tmp: _ISOLATED_SERVE, lambda tmp: None),
    (lambda tmp: [a for a in _ISOLATED_SERVE if a != "--isolated"], lambda tmp: _rehomed(tmp)),
    (lambda tmp: [*_ISOLATED_SERVE, "--stop"], lambda tmp: _rehomed(tmp)),
    (lambda tmp: ["-m", "hermes_cli.main", "--isolated", "serve"], lambda tmp: _rehomed(tmp)),
    (lambda tmp: ["-m", "hermes_cli.main", "harness", "serve", "--isolated"], lambda tmp: _rehomed(tmp)),
], ids=["real-home", "real-hermes-root", "home-unset", "inherited-env", "unisolated", "stop",
        "isolated-before-serve", "harness-serve"])
def test_a_serve_the_sandbox_does_not_cover_is_refused(tmp_path, argv, env):
    with pytest.raises(RuntimeError, match="would START a hermes backend"):
        subprocess.Popen([str(tmp_path / "python3"), *argv(tmp_path)], env=env(tmp_path),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
