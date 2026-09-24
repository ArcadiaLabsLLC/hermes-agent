"""Fork-owned tests moved out of ``tests/hermes_cli/test_pip_install_detection.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""



def test_stamp_install_method_writes_code_scoped(tmp_path, monkeypatch):
    from hermes_cli.install_method import stamp_install_method
    home = tmp_path / "profile"
    code = tmp_path / "code"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    stamp_install_method("git", project_root=code)
    assert (code / ".install_method").read_text(encoding="utf-8") == "git\n"
    assert not (home / ".install_method").exists()
