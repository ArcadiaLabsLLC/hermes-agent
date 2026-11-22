"""ripgrep's matcher, loaded in process: the ctypes binding of ``crates/project_files_match`` (ABI 1).

Row ``RT-PHONE-REGEX-SEARCH-RUNS-RIPGREPS-MATCHER-FROM-A-NATIVE-LIBRARY`` (plan
``docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md`` §5). A phone's
``search_files`` runs a regular expression here first (``phone_file_tools._content_matcher``); the
fallback is ``fallback_match``, and Python ``re`` never runs on a caller's pattern.

* **Bytes, never a path.** Python's walk picks the files and ``reader.read_regular_file`` opens them;
  the library gets each file's bytes and answers its matching line numbers.
* **One owner per handle.** A :class:`RegexLines` holds its compiled pattern's handle, frees it once
  (:meth:`RegexLines.close`, a ``with`` block's end, or collection) and never passes it after; the
  library can refuse only a NULL handle, never a freed one.
* **The GIL is released** for every call (``ctypes.CDLL``), so other Python threads run during a search.
* **Time.** :class:`patterns.Deadline` owns the clock: each call is handed the milliseconds left and
  is refused ``search_timeout`` when they run out.
* **Cancel.** A :class:`Cancel` is one byte the library reads before each call, at each match and at
  the end. Between files (before each call) :meth:`Cancel.check` reads the turn's interrupt,
  ``tools.interrupt.is_interrupted()``, on the calling thread and sets the byte. During a call the byte
  is set only by :meth:`Cancel.set` from another thread holding the same ``Cancel``; nothing in a turn
  does that today, so in a turn one call is bounded by its per-file cap (``MAX_READ_BYTES``, 5 MiB:
  about 1-9 ms on the Linux box, ran) and by the milliseconds it was handed.
* **Where the library is.** ``ETERNIA_PROJECT_FILES_MATCH_LIB`` names it (CI's host build, a lane's live
  read). With no library this module is unavailable, says why once in the log, and the search falls
  back. How a phone ships the library is row ``RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID``.
"""

from __future__ import annotations

__layer__ = "stores"

import ctypes
import logging
import os
import threading
from collections.abc import Callable

from agent_runtime.project_files.patterns import Deadline
from agent_runtime.project_files.rules import ProjectFileRefusal

__all__ = ["ABI_VERSION", "LIBRARY_ENV", "Cancel", "NativeMatchError", "RegexLines", "SearchCancelled",
           "available", "unavailable_reason"]

logger = logging.getLogger(__name__)

#: The environment variable naming the library file.
LIBRARY_ENV = "ETERNIA_PROJECT_FILES_MATCH_LIB"
#: The ABI this binding speaks (``pfm_abi_version``).
ABI_VERSION = 1
#: The compiled program's size cap and the lazy DFA's cache cap (plan §5: start at 1 MiB and 8 MiB;
#: ``\p{L}{30}c`` is refused at 1 MiB, ran). The nesting limit (64) is the library's own.
SIZE_LIMIT = 1 << 20
DFA_LIMIT = 8 << 20
#: Line numbers one call may hand back; a file with more is searched again from where it stopped.
LINES_CAP = 4096
_ERROR_CAP = 1024
_U32_MAX = (1 << 32) - 1

_CANCELLED, _BUDGET_SPENT = -1, -2


class SearchCancelled(Exception):
    """The search was stopped: the turn was interrupted, or its ``Cancel`` was set."""


class NativeMatchError(RuntimeError):
    """The library answered a code no correct call gets (a caught panic, a refused search)."""


class Cancel:
    """One search's cancel byte, read by the library; :meth:`check` reads ``probe`` between calls."""

    def __init__(self, probe: Callable[[], bool] | None = None) -> None:
        self.byte = ctypes.c_uint8(0)
        self._probe = probe

    def set(self) -> None:
        """Stop the search at its next match (any thread)."""

        self.byte.value = 1

    @property
    def is_set(self) -> bool:
        return self.byte.value != 0

    def check(self) -> None:
        """Set the byte when ``probe`` says the turn was interrupted; raise once it is set."""

        if not self.is_set and self._probe is not None and self._probe():
            self.set()
        if self.is_set:
            raise SearchCancelled("the search was stopped: the turn was interrupted")


def turn_cancel() -> Cancel:
    """A :class:`Cancel` that reads the calling turn's interrupt (``tools.interrupt.is_interrupted``)."""

    from tools.interrupt import is_interrupted

    return Cancel(is_interrupted)


class _Library:
    """The loaded library with its four prototypes declared."""

    def __init__(self, path: str) -> None:
        lib = ctypes.CDLL(path)
        lib.pfm_abi_version.argtypes = []
        lib.pfm_abi_version.restype = ctypes.c_int32
        version = lib.pfm_abi_version()
        if version != ABI_VERSION:
            raise OSError(f"{path} speaks ABI {version}, this binding speaks {ABI_VERSION}")
        lib.pfm_compile.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_size_t,
                                    ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t,
                                    ctypes.POINTER(ctypes.c_size_t)]
        lib.pfm_compile.restype = ctypes.c_void_p
        lib.pfm_search.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_size_t,
                                   ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
                                   ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_uint64)]
        lib.pfm_search.restype = ctypes.c_int64
        lib.pfm_free.argtypes = [ctypes.c_void_p]
        lib.pfm_free.restype = None
        self.lib = lib
        self.path = path


_state_lock = threading.Lock()
_loaded: dict[str, _Library | str] = {}  # library path (or "") -> the library, or why it is not there


def _library() -> _Library | str:
    """The library named by ``LIBRARY_ENV``, loaded once per path; else the reason, logged once."""

    path = os.environ.get(LIBRARY_ENV, "").strip()
    with _state_lock:
        if path in _loaded:
            return _loaded[path]
        if not path:
            found: _Library | str = f"{LIBRARY_ENV} is not set"
        else:
            try:
                found = _Library(path)
            except OSError as error:
                found = f"{path} did not load: {error}"
        if isinstance(found, str):
            logger.info("ripgrep's matcher is not available here (%s); regex search falls back", found)
        _loaded[path] = found
        return found


def available() -> bool:
    """Whether ripgrep's matcher is loaded (or loads now)."""

    return not isinstance(_library(), str)


def unavailable_reason() -> str | None:
    found = _library()
    return found if isinstance(found, str) else None


class RegexLines:
    """One compiled pattern and the one owner of its native handle."""

    def __init__(self, library: _Library, handle: int, pattern: str, cancel: Cancel) -> None:
        self._library = library
        self._handle: int | None = handle
        self._lock = threading.Lock()
        self.pattern = pattern
        self.cancel = cancel

    @classmethod
    def compile(cls, pattern: str, *, ignore_case: bool = False, cancel: Cancel | None = None) -> RegexLines:
        """``pattern`` compiled by ripgrep's matcher, or refused ``bad_argument`` with the engine's sentence.

        Raises ``NativeMatchError`` when the library is not available (ask :func:`available` first)."""

        library = _library()
        if isinstance(library, str):
            raise NativeMatchError(library)
        raw = pattern.encode("utf-8")
        error = ctypes.create_string_buffer(_ERROR_CAP)
        length = ctypes.c_size_t(0)
        handle = library.lib.pfm_compile(raw, len(raw), 1 if ignore_case else 0, SIZE_LIMIT, DFA_LIMIT,
                                         error, _ERROR_CAP, ctypes.byref(length))
        if not handle:
            sentence = error.raw[:length.value].decode("utf-8", "replace").strip()
            raise ProjectFileRefusal("bad_argument", f"the regex is refused: {sentence or 'unknown reason'}")
        return cls(library, handle, pattern, cancel or Cancel())

    def __enter__(self) -> RegexLines:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        """Free the handle, once; the object is unusable after."""

        with self._lock:
            handle, self._handle = self._handle, None
            # MUTATION: free without forgetting the handle and a second close frees it twice
            # (test_project_files_native_match: test_a_handle_is_freed_once_and_never_passed_after).
            if handle is not None:
                self._library.lib.pfm_free(handle)

    def line_numbers(self, data: bytes, deadline: Deadline | None = None) -> list[int]:
        """The 1-based numbers of the lines of ``data`` the pattern matches, ascending, every one of them.

        A file with more than ``LINES_CAP`` matching lines is searched again from where the cap stopped
        it, so nothing is cut short. Before each call the cancel is checked (raising
        :class:`SearchCancelled`) and the deadline asked; each call is handed what is left of it."""

        deadline = deadline or Deadline()
        out = (ctypes.c_uint64 * LINES_CAP)()
        resume_at, resume_line = ctypes.c_size_t(0), ctypes.c_uint64(0)
        start, first, numbers = 0, 1, []
        with self._lock:
            # MUTATION: pass the handle after close and the library is handed a freed pointer
            # (test_project_files_native_match: test_a_handle_is_freed_once_and_never_passed_after).
            if self._handle is None:
                raise NativeMatchError("this pattern was closed")
            while True:
                self.cancel.check()
                deadline.check()
                budget = min(_U32_MAX, max(1, deadline.remaining_ms()))
                written = self._library.lib.pfm_search(
                    self._handle, data, len(data), start, first, ctypes.byref(self.cancel.byte), budget,
                    out, LINES_CAP, ctypes.byref(resume_at), ctypes.byref(resume_line))
                if written == _CANCELLED:
                    raise SearchCancelled("the search was stopped: the turn was interrupted")
                if written == _BUDGET_SPENT:
                    raise deadline.refusal()
                if written < 0:
                    raise NativeMatchError(f"ripgrep's matcher answered code {written}")
                numbers.extend(out[:written])
                # MUTATION: return at the cap and a file with more matching lines than LINES_CAP is cut short
                # (test_project_files_native_match: test_a_file_past_the_lines_cap_is_resumed_not_cut).
                if resume_line.value == 0:
                    return numbers
                start, first = resume_at.value, resume_line.value

    def matching_lines(self, text: str, lines: list[str], deadline: Deadline | None = None) -> list[int]:
        """``replies.LineMatcher``: the indexes of ``lines`` (``text`` split on ``\\n``) the pattern matches."""

        return [number - 1 for number in self.line_numbers(text.encode("utf-8"), deadline)]
