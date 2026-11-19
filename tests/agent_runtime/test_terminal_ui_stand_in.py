"""The phone's ``rich``/``prompt_toolkit`` stand-in (``agent_runtime.terminal_ui_stand_in``,
RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT): installed only where it must be, and upstream's
terminal-UI reads answer as a device with no terminal UI.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``ensure_terminal_ui_stand_in`` drops the ``provider_sdks_enabled()`` check -> desktop test red.
* ``get_app_or_none`` answers an object -> the no-TUI read test red.
* ``TerminalUiUnavailable`` derives from ``RuntimeError`` -> the guarded-site test red.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agent_runtime import terminal_ui_stand_in as stand_in


def _phone_profile() -> None:
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"agent": {"provider_sdks": False}}), encoding="utf-8")


@pytest.fixture
def no_terminal_ui(monkeypatch):
    """No real rich/prompt_toolkit importable (the phone); every entry restored afterwards."""
    for name in [n for n in sys.modules if n.split(".")[0] in ("rich", "prompt_toolkit")]:
        monkeypatch.delitem(sys.modules, name)
    for name in stand_in.stand_in_modules():
        monkeypatch.setitem(sys.modules, name, None)  # recorded, so teardown puts the real one back
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(stand_in, "_real_terminal_ui_importable", lambda: False)
    return monkeypatch


def test_the_desktop_profile_installs_nothing(no_terminal_ui):
    assert stand_in.ensure_terminal_ui_stand_in() is False  # agent.provider_sdks defaults on
    assert not stand_in.is_stand_in(sys.modules.get("rich"))

    _phone_profile()  # positive control: the same call on the phone profile installs it
    assert stand_in.ensure_terminal_ui_stand_in() is True
    assert stand_in.is_stand_in(sys.modules["rich"]) and stand_in.is_stand_in(sys.modules["prompt_toolkit.utils"])


def test_a_real_terminal_ui_is_never_shadowed(no_terminal_ui):
    _phone_profile()
    no_terminal_ui.setattr(stand_in, "_real_terminal_ui_importable", lambda: True)
    assert stand_in.ensure_terminal_ui_stand_in() is False
    assert not stand_in.is_stand_in(sys.modules.get("rich"))


def test_upstream_tui_reads_take_their_no_tui_path(no_terminal_ui, tmp_path):
    """No prompt_toolkit application owns a terminal; no stream is a patch_stdout proxy; a cell
    width is the real one."""
    for name, module in stand_in.stand_in_modules().items():
        no_terminal_ui.setitem(sys.modules, name, module)
    from prompt_toolkit.application.current import get_app_or_none
    from prompt_toolkit.utils import get_cwidth

    from agent.display import KawaiiSpinner

    assert get_app_or_none() is None
    assert KawaiiSpinner("x")._is_patch_stdout_proxy() is False
    assert get_cwidth("a中") == 3
    assert stand_in.is_stand_in(sys.modules["rich.console"])


def test_a_drawing_call_raises_an_import_error_a_guarded_site_catches(no_terminal_ui):
    for name, module in stand_in.stand_in_modules().items():
        no_terminal_ui.setitem(sys.modules, name, module)
    from rich.console import Console
    from rich.markup import escape

    try:
        Console()
    except ImportError as exc:  # the shape every `except ImportError` guard upstream already handles
        assert "no terminal UI" in str(exc)
    else:
        raise AssertionError("Console() drew on a device with no terminal UI")
    with pytest.raises(ImportError):
        escape("[b]")
    assert issubclass(type("Sub", (Console,), {}), Console)  # subclassable at import, as upstream's mixins do
