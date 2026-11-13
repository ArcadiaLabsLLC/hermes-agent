"""RT-QA-FIXTURE-CLARIFY-FAILS-IN-RELAYED-TURN: the fixture recipe that makes a relayed teammate ask back.

Seen live 2026-11-12 (w1112b-cttfu): a relayed ``[[qa:tool clarify {"question": …, "choices": …}]]`` showed
"1 failed" and no question reached the asker. Cause (read in code, then read live by w1112b-hm): ``clarify``
takes ``questions=[{question, choices?}]``; the flat shape is refused by ``_normalize_questions``. With the
recipe below a relayed QA Agent A's question reached Base as "QA Agent A asked: Blue or green? • Blue • Green".
The same recipe is written in Eternia ``docs/agent_context/STAGEC_QA.md``.
"""

from __future__ import annotations

import json

from tools.clarify_tool import clarify_tool

#: The directive's JSON, exactly as the recipe gives it (nested in an agent_chat_send message, its closing
#: ``]]`` is written ``]]`` so the outer directive does not end there).
RECIPE_ARGS = '{"questions": [{"question": "Blue or green?", "choices": ["Blue", "Green"]}]}'
FLAT_ARGS = '{"question": "Blue or green?", "choices": ["Blue", "Green"]}'


def test_the_recipe_shape_asks_and_the_flat_shape_names_the_shape_to_send():
    """Mutation: the recipe in the flat shape -> no question is asked, red."""
    asked = []

    def callback(questions):
        asked.extend(questions)
        return {"answers": {"q0": "Blue"}, "outcome": "answered"}

    answer = json.loads(clarify_tool(json.loads(RECIPE_ARGS)["questions"], callback=callback))
    assert [q["question"] for q in asked] == ["Blue or green?"]
    assert answer["responses"][0]["user_response"] == "Blue"
    refused = clarify_tool(json.loads(FLAT_ARGS).get("questions"), callback=callback)
    assert "questions must be a non-empty array" in refused and len(asked) == 1
