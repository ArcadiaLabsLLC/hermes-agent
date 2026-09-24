"""Fork-owned tests moved out of ``tests/tools/test_local_env_windows_msys.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from tools.environments import local as local_mod
from tools.environments.local import (
    _shell_arg_safe_path,
)


class TestShellArgSafePath:
    """Program arguments are a different consumer class from script text.

    ``_bash_safe_path`` targets bash's own constructs (source/redirect/cd),
    where ``/c/...`` is right. Arguments reach native Windows binaries (``rg``,
    ``python.exe``) that cannot resolve ``/c/...`` — and
    ``_apply_windows_msys_bash_env_defaults`` sets ``MSYS_NO_PATHCONV=1`` so
    MSYS never converts it back for them.
    """

    def test_native_backslash_path_becomes_drive_qualified_forward_slashes(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        assert _shell_arg_safe_path(r"C:\Users\alice\notes.txt") == "C:/Users/alice/notes.txt"

    def test_forward_slash_drive_path_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        assert _shell_arg_safe_path("C:/Users/alice/notes.txt") == "C:/Users/alice/notes.txt"

    def test_msys_and_mixed_forms_fold_to_the_native_resolvable_form(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        assert _shell_arg_safe_path("/c/Users/alice/notes.txt") == "C:/Users/alice/notes.txt"
        assert _shell_arg_safe_path(r"/c/Users/alice\notes.txt") == "C:/Users/alice/notes.txt"

    def test_non_drive_arguments_survive_verbatim(self, monkeypatch):
        """Only drive-qualified paths are rewritten.

        The same helper quotes search patterns and ``python -c`` snippets;
        blanket backslash rewriting corrupted every regex containing one.
        """
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        assert _shell_arg_safe_path(r"absent\\npattern") == r"absent\\npattern"
        assert _shell_arg_safe_path("/tmp/foo") == "/tmp/foo"
        assert _shell_arg_safe_path("relative/dir") == "relative/dir"
        assert _shell_arg_safe_path("") == ""

    def test_no_op_off_windows(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", False)
        assert _shell_arg_safe_path(r"C:\Users\alice\notes.txt") == r"C:\Users\alice\notes.txt"
