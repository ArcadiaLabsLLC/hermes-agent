"""The autouse SessionDB template's contract (design sweep D3.11).

``tests/agent_runtime/_session_db_template.py`` is autouse for this directory:
a WRITER open of an absent store is seeded from the module's template, a READ
open of an absent store is untouched (it still fails and creates nothing), and
a test marked ``fresh_schema_path`` gets the production ``__init__`` alone.
"""

from __future__ import annotations

import pytest


def test_a_writer_open_of_an_absent_store_is_seeded_from_the_module_template(tmp_path):
    import hermes_state
    from tests.agent_runtime import _session_db_template as template

    path = tmp_path / "chat" / "state.db"
    hermes_state.SessionDB(db_path=path).close()

    assert path.exists()
    built = template._TEMPLATES[__file__]
    assert built.exists() and built != path


def test_a_read_open_of_an_absent_store_creates_nothing(tmp_path):
    import hermes_state

    path = tmp_path / "absent" / "state.db"
    with pytest.raises(Exception):
        hermes_state.SessionDB(db_path=path, read_only=True)

    assert not path.exists(), "a READ created the store"


def test_the_fixture_is_on_for_an_unmarked_test():
    import hermes_state

    assert hermes_state.SessionDB.__init__.__name__ == "seeded_init"


@pytest.mark.fresh_schema_path
def test_a_fresh_schema_path_test_gets_the_production_init():
    import hermes_state

    assert hermes_state.SessionDB.__init__.__name__ != "seeded_init"
