"""Fork-owned tests moved out of ``tests/tools/test_file_operations.py`` (lane CARRY).

Same names, same bodies; the upstream file is byte-identical to upstream.
"""


from tests.tools.test_file_operations import (  # noqa: F401 — upstream names the moved tests use
    file_ops,
    mock_env,
)


class TestShellFileOpsHelpers:

    def test_escape_shell_arg_normalizes_windows_paths_for_native_consumers(
        self, monkeypatch, file_ops,
    ):
        """Shell-arg paths land in NATIVE Windows binaries (rg, python.exe).

        Those cannot resolve the MSYS ``/c/...`` spelling, and Hermes sets
        MSYS_NO_PATHCONV=1 on every bash spawn so nothing converts it back —
        so the arg form is the drive-qualified forward-slash one, which both
        the MSYS runtime and native binaries accept. Backslashes must still
        be gone (bash eats them), and the already-correct form is a no-op.
        """
        import tools.environments.local as local_mod

        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        # native backslash path -> drive-qualified forward slashes
        assert file_ops._escape_shell_arg(
            r"C:\Users\alice\notes.txt"
        ) == "'C:/Users/alice/notes.txt'"
        # already forward-slash: unchanged, still no backslashes
        assert file_ops._escape_shell_arg(
            "C:/Users/alice/notes.txt"
        ) == "'C:/Users/alice/notes.txt'"
        # mixed MSYS leftover -> same drive-qualified form
        assert file_ops._escape_shell_arg(
            r"/c/Users/alice\notes.txt"
        ) == "'C:/Users/alice/notes.txt'"

    def test_escape_shell_arg_leaves_non_path_arguments_verbatim(self, monkeypatch, file_ops):
        """Only drive-qualified paths are rewritten.

        ``_escape_shell_arg`` also quotes search patterns and ``python -c``
        snippets; blanket backslash rewriting corrupted every regex
        containing a backslash on Windows.
        """
        import tools.environments.local as local_mod

        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        assert file_ops._escape_shell_arg(r"absent\\npattern") == r"'absent\\npattern'"
        assert file_ops._escape_shell_arg("relative/dir") == "'relative/dir'"
        assert file_ops._escape_shell_arg("/tmp/posix") == "'/tmp/posix'"
