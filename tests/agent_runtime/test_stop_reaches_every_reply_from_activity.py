"""``RT-STOP-REACHES-EVERY-RUNNING-REPLY-THROUGH-ONE-SEAM``, the Activity door's half of the table.

The same starters and the same expected answer as the conversation Stop's half
(``test_stop_reaches_every_reply_through_one_seam.py``, which states the row, the table and the killing
mutations); here each reply is stopped through ``runtime.work.cancel`` on its chat-turn row. A file of its
own only so the two halves run on two workers.
"""

from __future__ import annotations

import pytest

from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # noqa: F401 (fixtures)
from tests.agent_runtime.test_stop_reaches_every_reply_through_one_seam import (  # noqa: F401 (fixtures)
    STARTERS, chat, chat_head, model, stop_the_reply,
)

pytestmark = pytest.mark.timeout(180)


@pytest.mark.parametrize("starter", STARTERS, ids=list(STARTERS))
def test_the_activity_cancel_ends_the_reply_whoever_started_it(chat, model, starter):
    stop_the_reply(chat, model, starter, "Activity cancel")
