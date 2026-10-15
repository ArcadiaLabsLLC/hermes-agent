"""Fork-owned tests moved out of ``tests/tools/test_approval.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import os
import shlex
import tempfile
from pathlib import Path
from unittest.mock import patch as mock_patch
import pytest
from tools import path_identity
from tools.approval_detection import _is_verification_artifact_cleanup, _windows_spelling_of_msys_path
from tools.approval import detect_dangerous_command



def _rm_f(path) -> str:
    """Spell ``rm -f <path>`` the way a shell argument is actually spelled.

    The exemption tokenizes with ``shlex.split(posix=True)``, which eats a
    bare Windows separator (``C:\\Temp\\x`` -> ``C:Tempx``). Quoting is how a
    caller passes such a path through a POSIX-tokenized command line, and it
    keeps this fixture identical on POSIX (no metacharacters -> unquoted).
    """
    return f"rm -f {shlex.quote(str(path))}"


_WINDOWS_ONLY = pytest.mark.skipif(
    os.name != "nt",
    reason="the MSYS spelling only reaches approval where _find_shell() runs Git Bash",
)


def _msys_spelling(windows_path: str) -> str:
    """Spell a drive-rooted Windows path the way Git Bash does.

    ``C:\\Users\\x`` -> ``/c/Users/x``. Derived from the platform's own temp
    dir rather than hardcoded, so the fixture names the real directory the
    exemption is about.
    """
    drive, tail = os.path.splitdrive(windows_path)
    assert drive, f"not a drive-rooted Windows path: {windows_path!r}"
    return "/" + drive[0].lower() + tail.replace("\\", "/")


class TestDetectDangerousRm:
    def test_exemption_rejects_in_temp_symlink_pointing_outside_temp(self, tmp_path):
        """A correctly-spelled temp artifact that RESOLVES outside temp is not exempt.

        ``_is_verification_artifact_cleanup`` has two independent guards: the
        literal-spelling equality above, and a realpath check that the operand
        still lands in the temp dir after symlink resolution. Only the first
        had a test — deleting the realpath guard entirely left the whole
        TestDetectDangerousRm class green, so this pins the second one.
        """
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("do not touch", encoding="utf-8")

        # Correctly named, correctly located, correctly spelled -- but a
        # symlink whose target is outside the temp dir.
        planted = temp_dir / "hermes-verify-example.py"
        planted.symlink_to(secret)

        with mock_patch("tempfile.gettempdir", return_value=str(temp_dir)):
            assert _is_verification_artifact_cleanup(_rm_f(planted)) is False

    def test_exemption_identity_half_is_not_a_prefix_test(self, tmp_path):
        """A neighbour whose name EXTENDS temp's must not read as inside temp.

        The identity half of the exemption ("does the operand still resolve into
        the temp dir") now goes through ``path_identity.denotes_same_file``
        instead of a string ``!=``. Migrating an identity question is exactly
        where a prefix-shaped answer can be smuggled in, so pin the shape that
        would expose one: ``<temp>-evil`` shares every character of ``<temp>``
        and must still be refused.

        The control above it is what makes the refusal meaningful — an
        identically shaped artifact in the same directory IS exempt, so the
        rejection is the identity guard firing rather than the whole lane being
        inert.
        """
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        neighbour = tmp_path / "temp-evil"
        neighbour.mkdir()
        secret = neighbour / "hermes-verify-example.py"
        secret.write_text("do not touch", encoding="utf-8")

        real_temp = os.path.realpath(temp_dir)
        planted = os.path.join(real_temp, "hermes-verify-example.py")
        try:
            Path(planted).symlink_to(secret)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation unavailable for this user")
        plain = os.path.join(real_temp, "hermes-verify-plain.py")
        Path(plain).write_text("", encoding="utf-8")

        with mock_patch("tempfile.gettempdir", return_value=real_temp):
            assert _is_verification_artifact_cleanup(_rm_f(plain)) is True
            assert _is_verification_artifact_cleanup(_rm_f(planted)) is False

    @_WINDOWS_ONLY
    def test_msys_spelled_temp_artifact_cleanup_is_exempt(self):
        """Git Bash spells the very same temp file ``/c/Users/.../Temp/x``.

        ``_find_shell()`` returns Git Bash on Windows, so THAT is the spelling
        the cleanup command actually arrives in. It could never be exempted
        before -- the exemption only knew ``C:\\Users\\...`` -- and unlike a
        Windows-native path it also matches "delete in root path" (leading
        "/"), so agents hit a real refusal on routine cleanup.
        """
        temp_dir = os.path.realpath(tempfile.gettempdir())
        msys_temp = _msys_spelling(temp_dir)
        with mock_patch("tempfile.gettempdir", return_value=temp_dir):
            for prefix in ("hermes-verify-", "hermes-ad-hoc-"):
                command = _rm_f(f"{msys_temp}/{prefix}example.py")
                # Assert the exemption FIRED, not merely that the verdict was
                # permissive.
                assert _is_verification_artifact_cleanup(command) is True
                assert detect_dangerous_command(command) == (False, None, None)
            # ...and that the exemption is the ONE mechanism doing the work:
            # an identically-spelled non-artifact in the same directory is
            # still flagged, so the permissive verdicts above are not the
            # pattern engine simply having nothing to say about this shape.
            assert detect_dangerous_command(
                _rm_f(f"{msys_temp}/not-a-hermes-artifact.py")
            )[0] is True

    @_WINDOWS_ONLY
    def test_msys_translation_exempts_the_spelling_and_nothing_else(self):
        """The MSYS lane must refuse everything the native lane refuses.

        The rejection table from
        ``test_verification_cleanup_exemption_rejects_broader_deletions``,
        re-spelled the MSYS way: translating a spelling must not become a
        second, looser exemption.
        """
        temp_dir = os.path.realpath(tempfile.gettempdir())
        msys_temp = _msys_spelling(temp_dir)
        drive = msys_temp.split("/")[1]
        commands = (
            f"rm -rf {msys_temp}/hermes-verify-example.py",
            f"rm -f {msys_temp}/hermes-verify-example.py {msys_temp}/other.py",
            f"rm -f {msys_temp}/nested/../hermes-verify-example.py",
            f"rm -f {msys_temp}/../hermes-verify-example.py",
            f"rm -f /{drive}/hermes-verify-example.py",
            f"rm -f {msys_temp}/hermes-verify-*",
            f"rm -f {msys_temp}/hermes-verify-$(touch /tmp/pwned).py",
            f"rm -f {msys_temp}/hermes-ad-hoc-`touch /tmp/pwned`.py",
            f"rm -f {msys_temp}/hermes-verify-example.py; touch /tmp/pwned",
            f"rm -f {msys_temp}/example.py",
        )
        with mock_patch("tempfile.gettempdir", return_value=temp_dir):
            for command in commands:
                assert _is_verification_artifact_cleanup(command) is False, command
                is_dangerous, key, desc = detect_dangerous_command(command)
                assert is_dangerous is True, command
                assert key is not None, command
                assert "delete" in desc.lower(), command

    @_WINDOWS_ONLY
    def test_msys_exemption_rejects_in_temp_symlink_pointing_outside_temp(self, tmp_path):
        """The realpath guard survives the spelling translation.

        The MSYS lane re-runs the SAME two guards, so a correctly named,
        correctly located artifact that RESOLVES outside temp stays refused --
        exactly as the native-spelling pin above requires.
        """
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("do not touch", encoding="utf-8")

        planted = temp_dir / "hermes-verify-example.py"
        planted.symlink_to(secret)
        plain = temp_dir / "hermes-verify-plain.py"
        plain.write_text("", encoding="utf-8")

        real_temp = os.path.realpath(temp_dir)
        msys_temp = _msys_spelling(real_temp)
        with mock_patch("tempfile.gettempdir", return_value=real_temp):
            # Control: a plain file of the same shape in the same directory IS
            # exempt through the MSYS spelling, so the rejection below is the
            # realpath guard and not the translation failing to happen at all.
            assert _is_verification_artifact_cleanup(
                _rm_f(f"{msys_temp}/hermes-verify-plain.py")
            ) is True
            assert _is_verification_artifact_cleanup(
                _rm_f(f"{msys_temp}/hermes-verify-example.py")
            ) is False

    def test_msys_translation_is_windows_only_and_narrow(self):
        """``/c/...`` is a real POSIX path; only Windows may reinterpret it.

        The platform gate moved with the function into ``tools.path_identity``
        (approval re-exports it), so the patch target is the authority's global.
        The imported ``_windows_spelling_of_msys_path`` name below is the same
        object — pinning it here keeps the guarantee attached to the guard that
        depends on it, not only to the module that implements it.
        """
        with mock_patch.object(path_identity, "_IS_WINDOWS", True):
            assert _windows_spelling_of_msys_path("/c/Users/x/hermes-verify-a.py") == (
                r"C:\Users\x\hermes-verify-a.py"
            )
            # Not an MSYS drive path: a multi-character first component.
            assert _windows_spelling_of_msys_path("/tmp/hermes-verify-a.py") is None
            # Relative and bare-root spellings name no file to remove.
            assert _windows_spelling_of_msys_path("c/Users/x") is None
            assert _windows_spelling_of_msys_path("/c/") is None
            # Already carries a native separator -- not a clean MSYS spelling.
            assert _windows_spelling_of_msys_path("/c/Users\\x") is None
        with mock_patch.object(path_identity, "_IS_WINDOWS", False):
            assert _windows_spelling_of_msys_path("/c/Users/x/hermes-verify-a.py") is None
