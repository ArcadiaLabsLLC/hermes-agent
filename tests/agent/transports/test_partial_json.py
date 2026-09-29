"""``parse_partial_json`` against ``jiter.from_json(partial_mode=True)``, the parser the ``anthropic`` SDK uses.

Measured, not asserted: every input goes to both, and the result — or the error message the
loop's parse-retry path reads — must be identical. The battery covers each partial rule
(cut scalars dropped with their key, cut containers kept, a stray character after a value
ending the parse) and each error message ``jiter`` raises.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``string`` returns the text so far when the input ends inside it (a cut string kept) -> battery red.
* ``_after_member`` raises on a stray character instead of ending the parse            -> battery red.
* ``error`` counts a character's column from 0                                        -> battery red.
"""

from __future__ import annotations

import pytest

from agent.transports.partial_json import parse_partial_json

jiter = pytest.importorskip("jiter")

BATTERY = [
    '', ' ', '{', '{"', '{"a', '{"a"', '{"a":', '{"a": ', '{"a": 1', '{"a": 1.', '{"a": 1.5', '{"a": -', '{"a": 1e',
    '{"a": 1e5', '{"a": t', '{"a": tr', '{"a": true', '{"a": n', '{"a": nul', '{"a": null,', '{"a": null, "b',
    '{"a": [', '{"a": [1', '{"a": [1,', '{"a": [1, "x', '{"a": {"b": 2', '{"a": "x\\', '{"a": "x\\u00', '[1, 2',
    '"abc', '12', 'tr', '{"a": 1}', '{"a": 1} x', '{"a": 1}}', '{a: 1}', '{"a" 1}', '{"a": 1 "b": 2}', '[1 2]',
    '{"a": x}', '{"a": tx}', '{"a": 01}', '{"a": nope}', '{"a": [1,]}', '{"a": 1,}', '{"a":\n cron}',
    '{"a": "\x01"}', '{"a": -x}', '{"a": 1.e5}', '{"a": .5}', '{"a": "ab"', '{"a": {"b"', '{"a": {"b":',
    '{"a": {}', '{"a": []', '{,', '{"a": [1, {', '{"a": [1, {"b', '{"a": [1, {"b": 3', 'fals', 'false',
    '{"a":1}\n', '{"a":"\\ud83d', '{"a":"\\ud83d\\ude00"}', '{"a":1e999}', '{"a": -0}',
    '{"a": 12345678901234567890}', '{"a": 1.0}', '{"a": 1E2}', '{"a": 1e+', '{"a": 1e-2}', '{"a": trux}',
    '{"a": nulll}', '{"a": [tr', '{"names": cronjob_manage}', '{"a": "\\q"}', '{"a": 1, "a": 2}',
    '{"a": [1, 2]', '[', '[1,', '[{', '{"a": "b"} ', '  {"a": 1}  ', '{"a": 1.5e', '{"a": -1', '{"a": -1.',
    '\n{\n"a"\n:\n1', '{"a": "\\ud83d"}', '{"a": "\\uZZZZ"}', '{"path": "a.txt", "limit": [1, 2]}',
]


def _outcome(parse, text):
    try:
        return "ok", parse(text)
    except ValueError as exc:
        return "error", str(exc)


@pytest.mark.parametrize("text", BATTERY)
def test_each_input_parses_or_fails_exactly_as_jiter_does(text):
    expected = _outcome(lambda t: jiter.from_json(t.encode(), partial_mode=True), text)
    actual = _outcome(parse_partial_json, text)
    assert repr(actual) == repr(expected)  # repr: 1 and 1.0, inf and a dict's key order all count


def test_the_battery_exercises_every_rule():
    """Positive control: the battery is not all one outcome — it keeps, drops, stops and fails."""
    outcomes = [_outcome(parse_partial_json, text) for text in BATTERY]
    assert {"ok", "error"} == {kind for kind, _ in outcomes}
    assert parse_partial_json('{"a": [1, "x') == {"a": [1]}      # a cut scalar is dropped, its list kept
    assert parse_partial_json('{"a": 1 "b": 2}') == {"a": 1}     # a stray character ends the parse
    with pytest.raises(ValueError, match="expected value at line 1 column 11"):
        parse_partial_json('{"names": cronjob_manage}')
