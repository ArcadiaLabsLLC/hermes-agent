"""A phone agent's regex search runs ripgrep's matcher in process, bounded and cancellable.

Row ``RT-PHONE-REGEX-SEARCH-RUNS-RIPGREPS-MATCHER-FROM-A-NATIVE-LIBRARY`` (plan
``docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md``, review w1118a.87).
The order is the owner's ruling: ripgrep's matcher (``native_match``), else the ``regex`` package with
``timeout=`` (``fallback_match``), else a refusal in words; never Python ``re`` on the caller's pattern.

* The native tests load the host build named by ``ETERNIA_PROJECT_FILES_MATCH_LIB``
  (``rust-tests.yml`` builds it and runs this file); unset, they skip with that reason.
* The real ``regex`` package tests skip where it does not import (no test venv here has it: uv.lock
  carries it only through the opt-in ``kittentts`` extra). The fallback's wiring runs always, over a
  stand-in package.
* The refusal and the never-``re`` tests always run, with both engines forced away.

Killing mutations are named at each test and in the code.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from agent_runtime import phone_file_tools as tools
from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.project_files import fallback_match, native_match
from agent_runtime.project_files.patterns import Deadline
from agent_runtime.project_files.rules import ProjectFileRefusal
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slots import bind, declare

T0 = "2026-11-21T12:00:00+00:00"

native = pytest.mark.skipif(
    not native_match.available(),
    reason=f"no host build of crates/project_files_match is loaded ({native_match.unavailable_reason()}); "
           "rust-tests.yml builds one and runs this file with ETERNIA_PROJECT_FILES_MATCH_LIB set")
regex_package = pytest.mark.skipif(
    not fallback_match.available(),
    reason="the regex package does not import here (uv.lock carries it only through the opt-in kittentts extra)")


def _call(tool, **args) -> dict:
    return json.loads(tool(args))


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """A phone project folder ``code`` bound on this device."""

    machine_roots_cache_clear()
    root = tmp_path / "repos" / "local" / "code"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.rs").write_text("fn main() {\n    helper(1);\n}\n\nfn helper(a: u8) {}\n", encoding="utf-8")
    (root / "notes.txt").write_bytes(b"buy milk\r\ncall mum\r\n")
    workspace = WorkspaceStore().create(name="Phone").id
    declare(workspace, [{"name": "code", "repo": {"clone_url": None, "local": True}}], issued_at=T0, machine="m")
    bind(workspace, "code", str(root), issued_at=T0)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)
    return root


def _no_fallback(monkeypatch) -> None:
    monkeypatch.setattr(fallback_match, "_package", lambda: None)


def _no_native(monkeypatch) -> None:
    monkeypatch.setattr(native_match, "available", lambda: False)


# ---- ripgrep's matcher (the host build) ----


@native
def test_a_phone_search_files_regex_runs_ripgreps_matcher(project, monkeypatch):
    """MUTATION (``phone_file_tools._content_matcher``): skip the native step, and with no fallback the
    regex is refused, red. ``$`` matches before ``\\r\\n`` (the crate's ``crlf(true)``)."""

    _no_fallback(monkeypatch)
    found = _call(tools.search_files, pattern=r"fn\s+\w+\(", path="code")
    assert [(m["path"], m["line"], m["text"]) for m in found["matches"]] == [
        ("code/src/main.rs", 1, "fn main() {"), ("code/src/main.rs", 5, "fn helper(a: u8) {}")]
    assert [m["line"] for m in _call(tools.search_files, pattern="milk$", path="code")["matches"]] == [1]
    (hit,) = _call(tools.search_files, pattern=r"^\s+helper\(\d\);$", path="code/src/main.rs", context=1)["matches"]
    assert hit["line"] == 2 and hit["before"] == [{"line": 1, "text": "fn main() {"}]
    assert hit["after"] == [{"line": 3, "text": "}"}]


@native
@pytest.mark.parametrize("pattern, words", [
    ("(", "unclosed group"),
    (r"\p{L}{30}c", "exceeds size limit"),
    (r"a\nb", r'the literal "\n" is not allowed in a regex'),
])
def test_a_refused_regex_answers_the_engines_sentence(project, pattern, words):
    """MUTATION (crate ``compile``): drop the size limit, and ``\\p{L}{30}c`` compiles, red."""

    refused = _call(tools.search_files, pattern=pattern, path="code")
    assert refused["code"] == "bad_argument" and words in refused["error"], refused


@native
def test_a_file_past_the_lines_cap_is_resumed_not_cut(project, monkeypatch):
    """A file with more matching lines than one call hands back is searched again from where it
    stopped, so offset paging gives what the literal path gives.

    MUTATION (``RegexLines.line_numbers``): return at the cap, and 3 of 10 lines are found, red."""

    monkeypatch.setattr(native_match, "LINES_CAP", 3)
    (project / "many.txt").write_text("".join(f"hit {n}\nmiss\n" for n in range(10)), encoding="utf-8")
    regex = _call(tools.search_files, pattern="hi[t]", path="code/many.txt")
    literal = _call(tools.search_files, pattern="hit", path="code/many.txt")
    assert regex["total_count"] == literal["total_count"] == 10
    assert regex["matches"] == literal["matches"]
    paged = _call(tools.search_files, pattern="hi[t]", path="code", offset=7, limit=5)
    assert [m["line"] for m in paged["matches"]] == [15, 17, 19]


@native
def test_a_handle_is_freed_once_and_never_passed_after():
    """MUTATION (``RegexLines.close``): free without forgetting the handle, and a second close frees it
    again, red. MUTATION (``RegexLines.line_numbers``): drop the closed check, and the library is handed
    the dead handle, red."""

    compiled = native_match.RegexLines.compile("a+")
    real = compiled._library.lib
    freed: list[int] = []

    class Spy:
        def __getattr__(self, name):
            return getattr(real, name)

        def pfm_free(self, handle):
            freed.append(handle)
            if len(freed) == 1:
                real.pfm_free(handle)

    handle = compiled._handle
    compiled._library = types.SimpleNamespace(lib=Spy())
    assert compiled.line_numbers(b"b\naa\n") == [2]
    compiled.close()
    compiled.close()
    del compiled  # collection closes too, and finds nothing left to free
    assert freed == [handle]
    closed = native_match.RegexLines.compile("a")
    closed.close()
    with pytest.raises(native_match.NativeMatchError, match="closed"):
        closed.line_numbers(b"a\n")


def _every_line(lines: int) -> bytes:
    return b"a\n" * lines


@native
def test_the_gil_is_released_during_a_call(monkeypatch):
    """Another Python thread keeps running while one native call searches.

    MUTATION (``_Library``): load with ``ctypes.PyDLL`` (which holds the GIL), and the ticker never
    runs during the call, red."""

    monkeypatch.setattr(native_match, "LINES_CAP", 1 << 21)  # one call, not one per 4096 lines
    compiled = native_match.RegexLines.compile("a")
    library = compiled._library
    ticks, during = [0], []
    started, done = threading.Event(), threading.Event()

    def tick():
        started.wait()
        while not done.is_set():
            ticks[0] += 1
            time.sleep(0.0005)

    def search(*args):
        started.set()
        before = ticks[0]
        try:
            return library.lib.pfm_search(*args)
        finally:
            during.append(ticks[0] - before)

    ticker = threading.Thread(target=tick)
    ticker.start()
    compiled._library = types.SimpleNamespace(lib=types.SimpleNamespace(pfm_search=search))
    try:
        found = compiled.line_numbers(_every_line(1 << 21), Deadline(30))
    finally:
        done.set()
        started.set()
        ticker.join()
        compiled._library = library
        compiled.close()
    assert len(found) == 1 << 21 and len(during) == 1
    assert during[0] >= 3, f"the ticker ran {during[0]} times during the native call"


@native
def test_a_cancel_set_during_a_call_stops_it_at_a_match(monkeypatch):
    """MUTATION (crate ``Lines::matched``): never read the byte at a match, and the call runs to its
    end before the cancel shows, red (the crate's own test reds too)."""

    monkeypatch.setattr(native_match, "LINES_CAP", 1 << 21)
    data = _every_line(1 << 21)
    whole = time.monotonic()
    native_match.RegexLines.compile("a").line_numbers(data, Deadline(30))
    whole = time.monotonic() - whole
    cancel = native_match.Cancel()
    compiled = native_match.RegexLines.compile("a", cancel=cancel)
    timer = threading.Timer(whole / 20, cancel.set)
    started = time.monotonic()
    timer.start()
    with pytest.raises(native_match.SearchCancelled):
        compiled.line_numbers(data, Deadline(30))
    took = time.monotonic() - started
    timer.join()
    assert took < whole / 2, f"stopped after {took:.3f} s; the whole call takes {whole:.3f} s"


@native
def test_an_interrupted_turn_stops_the_search_between_files(project, monkeypatch):
    """``tools.interrupt.is_interrupted()`` is read on the calling thread before each file's call.

    MUTATION (``RegexLines.line_numbers``): drop ``self.cancel.check()``, and the search answers, red."""

    from tools import interrupt

    interrupt.set_interrupt(True)
    try:
        stopped = _call(tools.search_files, pattern=r"fn\s", path="code")
    finally:
        interrupt.set_interrupt(False)
    assert stopped["code"] == "interrupted", stopped
    assert _call(tools.search_files, pattern=r"fn\s", path="code")["total_count"] == 2


@native
def test_each_call_is_handed_the_deadlines_remaining_time(monkeypatch):
    """A spent deadline refuses ``search_timeout`` before the call; a budget spent inside the call
    refuses it too. MUTATION (``RegexLines.line_numbers``): hand the library a fixed 10 s budget
    instead of the deadline's remaining time, and the second half answers, red."""

    monkeypatch.setattr(native_match, "LINES_CAP", 1 << 21)  # one long call, handed 1 ms

    compiled = native_match.RegexLines.compile("a")
    with pytest.raises(ProjectFileRefusal) as spent:
        compiled.line_numbers(b"a\n", Deadline(0.0))
    assert spent.value.code == "search_timeout"

    class Nearly(Deadline):
        def remaining_ms(self) -> int:
            return 1

    with pytest.raises(ProjectFileRefusal) as inside:
        native_match.RegexLines.compile(r"\w+\s\w+\s\d+$").line_numbers(b"abcd efgh 1234\n" * 2_000_000, Nearly(30))
    assert inside.value.code == "search_timeout"


# ---- the regex package fallback ----


class _StandIn:
    """A stand-in ``regex`` package: substring search, a TimeoutError for ``slow``, and what it was handed."""

    IGNORECASE = 2
    error = ValueError

    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    def compile(self, pattern, flags=0):
        if pattern == "(":
            raise self.error("missing ), unterminated subpattern at position 0")
        package = self

        class Compiled:
            def search(self, line, timeout=None):
                package.timeouts.append(timeout)
                if pattern.startswith("slow"):
                    raise TimeoutError("regex timed out")
                return line if pattern.strip("^$") in line else None

        return Compiled()


def test_the_fallback_runs_where_the_library_is_not_loaded(project, monkeypatch):
    """With no native library the ``regex`` package answers, each line handed the deadline's remaining
    time as ``timeout=``. MUTATION (``fallback_match``): drop ``timeout=``, and the package is handed
    no bound, red."""

    stand_in = _StandIn()
    _no_native(monkeypatch)
    monkeypatch.setattr(fallback_match, "_package", lambda: stand_in)
    found = _call(tools.search_files, pattern="^call mum$", path="code")
    assert [(m["path"], m["line"]) for m in found["matches"]] == [("code/notes.txt", 2)]
    assert stand_in.timeouts and all(0 < t <= 2.0 for t in stand_in.timeouts), stand_in.timeouts
    assert _call(tools.search_files, pattern="(", path="code")["code"] == "bad_argument"


def test_the_fallback_is_bounded_by_the_deadline(project, monkeypatch):
    """A match that runs out of time is refused ``search_timeout``, never answered in part.

    MUTATION (``RegexPackageLines.matching_lines``): catch nothing, and the TimeoutError escapes the tool, red."""

    _no_native(monkeypatch)
    monkeypatch.setattr(fallback_match, "_package", lambda: _StandIn())
    refused = _call(tools.search_files, pattern="slow.*", path="code")
    assert refused["code"] == "search_timeout", refused


@regex_package
def test_the_real_regex_package_stops_a_catastrophic_pattern_at_the_deadline():
    started = time.monotonic()
    lines = fallback_match.RegexPackageLines.compile(r"(a+)+$")
    with pytest.raises(ProjectFileRefusal) as refused:
        lines.matching_lines("", ["a" * 40 + "b"], Deadline(0.2))
    assert refused.value.code == "search_timeout" and time.monotonic() - started < 2.0


# ---- neither engine ----


def test_with_neither_engine_a_regex_is_refused_in_words_never_run_by_re(project, monkeypatch):
    """MUTATION (``phone_file_tools._content_matcher``): answer with a Python ``re`` matcher instead of
    the refusal, and ``re`` is handed the caller's pattern, red."""

    _no_native(monkeypatch)
    _no_fallback(monkeypatch)
    handed = []
    for name in ("compile", "search", "match", "fullmatch", "finditer", "findall"):
        real = getattr(re, name)

        def spy(pattern, *args, _real=real, **kwargs):
            if pattern in ("a.c", "milk$", r"fn\s+\w+\("):
                handed.append(pattern)
            return _real(pattern, *args, **kwargs)

        monkeypatch.setattr(re, name, spy)
    for pattern in ("a.c", "milk$", r"fn\s+\w+\("):
        refused = _call(tools.search_files, pattern=pattern, path="code")
        assert refused["code"] == "bad_argument", refused
        assert "needs ripgrep's matcher or the regex package" in refused["error"]
    assert handed == []
    assert _call(tools.search_files, pattern="buy milk", path="code")["total_count"] == 1, "plain text always works"


def test_the_binding_says_why_it_is_unavailable(monkeypatch):
    monkeypatch.setenv(native_match.LIBRARY_ENV, str(Path(sys.prefix) / "no-such-library.so"))
    assert not native_match.available()
    assert "did not load" in native_match.unavailable_reason()
    with pytest.raises(native_match.NativeMatchError):
        native_match.RegexLines.compile("a")


def test_building_many_matches_still_asks_the_deadline():
    """A whole-file matcher answers every matching line at once; turning them into replies asks the
    deadline per match, so a file matching on every line cannot run past it (the live read saw a 2000 ms
    search answer at 4010 ms before this). MUTATION (``replies.grep_lines``): drop the per-match check,
    and every line is answered after the deadline, red."""

    from agent_runtime.project_files.replies import grep_lines

    class Every:
        def matching_lines(self, text, lines, deadline=None):
            return list(range(len(lines)))

    class Spent(Deadline):
        calls = 0

        def check(self):
            Spent.calls += 1
            if Spent.calls > 10:
                raise self.refusal()

    with pytest.raises(ProjectFileRefusal) as refused:
        grep_lines("a.txt", "a\n" * 1000, Every(), Spent(30))
    assert refused.value.code == "search_timeout"
