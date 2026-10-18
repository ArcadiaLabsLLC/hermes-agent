"""The Lens MONITOR manifest: feeds, rules, automation policy, target persona.

Ported from Companion's ``monitor_manifest.dart`` (``MonitorManifest``,
``AutomationPolicy``, ``checkManifest``), reduced to the hermes contract (plan
``eternia-lens-in-hermes.md`` §3, rulings §6):

* ``automation`` is ``{level: notify|investigate, when: urgent|always,
  daily_turn_cap}``. The ``act`` level is out (ruling 3), so it is an unknown
  enum here, not a disabled option. The Work owner/scope/budget fields are cut.
* ``persona_id`` targets the forged turn; ``null`` means "the persona Mission
  Control has selected" (ruling 2), resolved at forge time, never stored.

The schema is CLOSED at every level: a manifest with one unknown key is refused,
as is a missing key, a duplicate feed or rule id, a rule naming a feed the
manifest does not carry, and a document over 64 KiB canonical.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from .feed import ValueKind, comparable_type, fx_feed_id, read_feed, value_type_of
from .rules import RuleForm, read_rule, rule_feed_ids
from .wire_value import (
    MAXIMUM_MANIFEST_BYTES,
    WireError,
    WireRefusal,
    bounded_int,
    bounded_list,
    canonical_bytes,
    checked_object,
    decode_strict_json,
    enum_value,
    opaque_id,
    optional,
    require,
)

__layer__ = "models"

MAXIMUM_FEEDS = 4
MAXIMUM_RULES = 16
#: A ceiling on the per-monitor daily turn cap: one turn per quarter hour.
MAXIMUM_DAILY_TURN_CAP = 96


class AutomationLevel(str, Enum):
    NOTIFY = "notify"
    INVESTIGATE = "investigate"


class AutomationWhen(str, Enum):
    URGENT = "urgent"
    ALWAYS = "always"


MANIFEST_KEYS = frozenset({"version", "monitor_id", "feeds", "rules", "automation", "persona_id"})
AUTOMATION_KEYS = frozenset({"level", "when", "daily_turn_cap"})


def read_automation(value: Any) -> dict[str, Any]:
    m = checked_object(value, AUTOMATION_KEYS)
    return {
        "level": enum_value(m["level"], AutomationLevel).value,
        "when": enum_value(m["when"], AutomationWhen).value,
        "daily_turn_cap": bounded_int(m["daily_turn_cap"], maximum=MAXIMUM_DAILY_TURN_CAP),
    }


def read_manifest(value: Any) -> dict[str, Any]:
    """The canonical manifest dict, or :class:`WireError` naming the first refusal."""

    m = checked_object(value, MANIFEST_KEYS)
    manifest = {
        "version": bounded_int(m["version"], minimum=1, maximum=1),
        "monitor_id": opaque_id(m["monitor_id"]),
        "feeds": bounded_list(m["feeds"], read_feed, minimum=1, maximum=MAXIMUM_FEEDS),
        "rules": bounded_list(m["rules"], read_rule, maximum=MAXIMUM_RULES),
        "automation": read_automation(m["automation"]),
        "persona_id": optional(m["persona_id"], opaque_id),
    }
    feed_ids = [feed["id"] for feed in manifest["feeds"]]
    require(len(set(feed_ids)) == len(feed_ids), "duplicate feed id")
    rule_ids = [rule["id"] for rule in manifest["rules"]]
    require(len(set(rule_ids)) == len(rule_ids), "duplicate rule id")
    require(all(set(rule_feed_ids(rule)) <= set(feed_ids) for rule in manifest["rules"]), "rule names an unknown feed")
    _check_typed_rules(manifest)
    if len(canonical_bytes(manifest)) > MAXIMUM_MANIFEST_BYTES:
        raise WireError(WireRefusal.OVER_BUDGET, "manifest byte budget")
    return manifest


#: The forms an instant feed admits: a deadline, or the deadline moving.
_INSTANT_FORMS = frozenset({RuleForm.ENDS_WITHIN, RuleForm.CHANGED, RuleForm.MOVED_BY})


def _check_typed_rules(manifest: dict[str, Any]) -> None:
    """A comparison is only between like values; a deadline rule only reads an instant (W5, W7)."""

    types = {feed["id"]: value_type_of(feed) for feed in manifest["feeds"]}
    for feed in manifest["feeds"]:
        rate = fx_feed_id(feed)
        # The dated exchange rate is a plain-number feed of this same monitor (W5).
        require(rate is None or (rate in types and rate != feed["id"]
                                 and types[rate]["kind"] == ValueKind.NUMBER.value), "fx feed")
    comparable = {feed["id"]: comparable_type(feed) for feed in manifest["feeds"]}
    for rule in manifest["rules"]:
        form = RuleForm(rule["form"])
        if form is RuleForm.BEST_OF:
            # Totals in one currency compare; shipping, tax and source currency may differ (W5).
            group = [comparable[feed] for feed in rule_feed_ids(rule)]
            require(all(t == group[0] for t in group), "best_of group mixes value types")
            require(group[0]["kind"] != ValueKind.INSTANT.value, "best_of over instants")
        instant = types[rule["feed_id"]]["kind"] == ValueKind.INSTANT.value
        require(instant or form is not RuleForm.ENDS_WITHIN, "ends_within reads an instant feed")
        require(not instant or form in _INSTANT_FORMS, "an instant is compared by deadline or by change")


def decode_manifest(source: str | bytes) -> dict[str, Any]:
    """Strict-decode then read: a duplicate key is refused before the dict forgets it."""

    return read_manifest(decode_strict_json(source, maximum_bytes=MAXIMUM_MANIFEST_BYTES))
