"""Fork-owned tests moved out of ``tests/test_hermes_constants.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from pathlib import Path
import hermes_constants
from hermes_constants import (
    get_default_hermes_root,
    reset_hermes_home_override,
    set_hermes_home_override,
)


class TestGetDefaultHermesRootMemo:
    """The memo over the two ``resolve()`` calls, and the two ways it could lie.

    Motivated by a measurement, not by taste: on the operator's Windows install
    (2026-09-08) one warm ``agent_runtime.snapshot`` build reached
    ``get_default_hermes_root`` 662 times, and each visit spent two
    ``nt._getfinalpathname`` calls (~71 us each — a handle open) re-answering an
    identical question. Memoising took the warm build from 608.8 ms to 411.0 ms
    on a paired A/B over the same store. See
    ``hermes_constants._DEFAULT_HERMES_ROOT_CACHE``.
    """

    @staticmethod
    def _counting_resolve(monkeypatch):
        """Replace ``Path.resolve`` with a counter over the real implementation."""

        calls: list[str] = []
        real = Path.resolve

        def counted(self, *args, **kwargs):
            calls.append(str(self))
            return real(self, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", counted)
        return calls

    @staticmethod
    def _pin_native_home(monkeypatch, native):
        """Pin the platform-native default — the memo key's second component.

        Patched at ``_get_platform_default_hermes_home`` rather than through
        ``Path.home()`` because that indirection is not platform-neutral: on
        win32 the native default comes from ``%LOCALAPPDATA%``, so a
        ``Path.home()`` fixture pins nothing there. This is also the exact value
        the key is built from, so the tests below speak about the key rather
        than about one platform's route to it.
        """

        monkeypatch.setattr(
            hermes_constants, "_get_platform_default_hermes_home", lambda: native
        )

    def test_repeat_calls_ask_the_filesystem_once(self, tmp_path, monkeypatch):
        """The second call resolves NOTHING — and the first one proves it could.

        The positive control is the first assertion. "Zero resolves on call two"
        is equally true of a function that never resolves at all, so a bare
        after-assertion would stay green if the whole containment branch were
        deleted; pinning that the FIRST call does resolve is what makes the
        second assertion a statement about the memo.
        """
        hermes_constants.reset_default_hermes_root_cache()
        root = tmp_path / ".hermes"
        (root / "profiles" / "coder").mkdir(parents=True)
        self._pin_native_home(monkeypatch, root)
        monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "coder"))
        calls = self._counting_resolve(monkeypatch)

        first = get_default_hermes_root()
        resolved_on_first = len(calls)
        calls.clear()
        second = get_default_hermes_root()

        assert resolved_on_first > 0, "control: the uncached call must hit the filesystem"
        assert calls == [], f"the memoised call re-resolved {calls}"
        assert first == second == root

    def test_the_key_carries_the_platform_default_not_just_hermes_home(
        self, tmp_path, monkeypatch
    ):
        """A ``Path.home()`` flip must re-answer, not replay.

        The failure this exists for is the cheap key: memoising on
        ``HERMES_HOME`` alone would leak the first answer across the
        per-test home fixture ``AGENTS.md`` prescribes for profile tests, so
        every later test in the process would read the first one's root.

        The inputs are chosen so the two arms genuinely DISAGREE: with
        ``HERMES_HOME`` at ``<a>/.hermes/sub``, a home of ``<a>`` puts it under
        the native root and the answer is ``<a>/.hermes``, while a home of
        ``<b>`` does not, and — the parent being ``.hermes`` rather than
        ``profiles`` — the answer is ``HERMES_HOME`` itself. A profile-shaped
        ``HERMES_HOME`` would have made both arms agree and the test vacuous.
        """
        hermes_constants.reset_default_hermes_root_cache()
        home_a = tmp_path / "a"
        home_b = tmp_path / "b"
        env_home = home_a / ".hermes" / "sub"
        env_home.mkdir(parents=True)
        (home_b / ".hermes").mkdir(parents=True)
        monkeypatch.setenv("HERMES_HOME", str(env_home))

        self._pin_native_home(monkeypatch, home_a / ".hermes")
        under_native = get_default_hermes_root()
        self._pin_native_home(monkeypatch, home_b / ".hermes")
        outside_native = get_default_hermes_root()

        assert under_native == home_a / ".hermes"
        assert outside_native == env_home

    def test_reset_makes_the_next_call_pay_again(self, tmp_path, monkeypatch):
        """``reset_default_hermes_root_cache`` forgets, for a test that moved a link."""
        hermes_constants.reset_default_hermes_root_cache()
        root = tmp_path / ".hermes"
        (root / "profiles" / "coder").mkdir(parents=True)
        self._pin_native_home(monkeypatch, root)
        monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "coder"))
        calls = self._counting_resolve(monkeypatch)

        get_default_hermes_root()
        calls.clear()
        get_default_hermes_root()
        assert calls == [], "control: the memo must be warm before the reset"

        hermes_constants.reset_default_hermes_root_cache()
        get_default_hermes_root()

        assert calls, "after the reset the next call must hit the filesystem again"


class TestSharedCharactersDir:
    """The install-wide character library, and the ladder it must ride.

    The library is ONE directory per hermes root — every persona profile under
    that root computes it from its own ``HERMES_HOME`` with no env injection,
    which is what makes a mis-resolved persona home stop being a characters
    incident (launcher plan §A-1 argument 1). The pins below are the two halves
    of that claim: convergence across profiles, and the ContextVar ladder the
    convergence has to be built on.
    """

    def test_profiles_under_one_root_converge_on_one_library(self, tmp_path, monkeypatch):
        root = tmp_path / ".hermes"
        (root / "profiles" / "alice").mkdir(parents=True)
        (root / "profiles" / "base").mkdir(parents=True)
        monkeypatch.delenv("HERMES_SHARED_CHARACTERS", raising=False)

        monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "alice"))
        alice = hermes_constants.get_shared_characters_dir()
        monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "base"))
        base = hermes_constants.get_shared_characters_dir()

        assert alice == root / "shared" / "characters"
        assert alice == base

    def test_a_bare_home_is_its_own_root(self, tmp_path, monkeypatch):
        """A home that is not ``<root>/profiles/<name>`` IS the root.

        This is the shape every test home and every plain-hermes install has,
        and it is what makes a tmpdir-scoped test isolated for free.
        """
        monkeypatch.delenv("HERMES_SHARED_CHARACTERS", raising=False)
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))

        assert hermes_constants.get_shared_characters_dir() == tmp_path / "home" / "shared" / "characters"

    def test_the_contextvar_override_is_the_home_the_library_derives_from(
        self, tmp_path, monkeypatch
    ):
        """The control on a bare-env implementation.

        ``get_default_hermes_root()`` reads ``os.environ["HERMES_HOME"]`` and
        never consults the context-local override, so a resolver built on it
        answers the PROCESS home while an in-process persona binding is scoped
        to another one — the cross-persona bleed the serve lane just retired.
        Two arms, and the second is the one that reds: an override under the
        same root must agree (nothing moved), and an override under a DIFFERENT
        root must answer THAT root's library.
        """
        monkeypatch.delenv("HERMES_SHARED_CHARACTERS", raising=False)
        process_root = tmp_path / "process"
        other_root = tmp_path / "other"
        (process_root / "profiles" / "base").mkdir(parents=True)
        (process_root / "profiles" / "alice").mkdir(parents=True)
        (other_root / "profiles" / "neko").mkdir(parents=True)
        monkeypatch.setenv("HERMES_HOME", str(process_root / "profiles" / "base"))

        token = set_hermes_home_override(process_root / "profiles" / "alice")
        try:
            same_root = hermes_constants.get_shared_characters_dir()
        finally:
            reset_hermes_home_override(token)
        token = set_hermes_home_override(other_root / "profiles" / "neko")
        try:
            foreign_root = hermes_constants.get_shared_characters_dir()
        finally:
            reset_hermes_home_override(token)

        assert same_root == process_root / "shared" / "characters"
        assert foreign_root == other_root / "shared" / "characters"

    def test_the_env_override_wins_over_derivation(self, tmp_path, monkeypatch):
        """An install-wide override is identical for every persona by definition.

        That is why a bare ``os.environ`` read is sound for THIS authority and
        not for the derivation below it: an operator/test that names the library
        has named it for the whole install, so there is no persona-scoped answer
        for a ContextVar to carry.
        """
        override = tmp_path / "custom-library"
        monkeypatch.setenv("HERMES_SHARED_CHARACTERS", str(override))
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes" / "profiles" / "alice"))

        assert hermes_constants.get_shared_characters_dir() == override
