"""RT-SESSIONS-EXPORT-READ-ONLY: `hermes sessions export` opens the SessionDB read-only.

Export only reads, and the launcher's QA owner-chat import runs it against the owner's live store,
so a writable open (schema migration, WAL churn) on that store is the defect. Fork-owned test of a
fork line in the upstream ``hermes_cli/sessions_cmd.py``.
"""

import json
from argparse import Namespace

from hermes_cli import sessions_cmd


def _export_args(**over):
    base = dict(
        sessions_action="export", session_id=None, format="jsonl", output="-", redact=False,
        dry_run=False, only=None,
    )
    base.update({name: None for name in sessions_cmd._FILTER_ARGS})
    base.update(over)
    return Namespace(**base)


def test_export_opens_the_store_read_only_and_still_exports(monkeypatch, tmp_path, capsys):
    import hermes_state

    db_path = tmp_path / "state.db"
    with hermes_state.SessionDB(db_path=db_path) as seed:
        seed.create_session("sess-export-ro", source="cli")
        seed.append_message("sess-export-ro", "user", "hello export")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))  # cmd_sessions opens <home>/state.db by path

    opened: list[bool] = []
    real = hermes_state.SessionDB

    def _spy(*args, **kwargs):
        opened.append(bool(kwargs.get("read_only", False)))
        return real(*args, **kwargs)

    monkeypatch.setattr(hermes_state, "SessionDB", _spy)
    sessions_cmd.cmd_sessions(_export_args(session_id="sess-export-ro"))

    assert opened == [True]
    first = capsys.readouterr().out.splitlines()[0]
    assert json.loads(first)["id"] == "sess-export-ro"


def test_export_on_a_fresh_profile_creates_no_store(monkeypatch, tmp_path, capsys):
    import hermes_state

    db_path = tmp_path / "state.db"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))  # cmd_sessions opens <home>/state.db by path
    sessions_cmd.cmd_sessions(_export_args())
    assert "No sessions found." in capsys.readouterr().out
    assert not db_path.exists()
