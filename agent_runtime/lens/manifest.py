"""The Lens MONITOR manifest: feeds, rules, automation policy, target persona.

Ported from Companion's ``monitor_manifest.dart`` (``MonitorManifest``,
``AutomationPolicy``, ``checkManifest``), reduced to the hermes contract (plan
``eternia-lens-in-hermes.md`` §3, rulings §6):

* ``automation`` is ``{level: notify|investigate, when: urgent|always,
  daily_turn_cap}`` plus the OPTIONAL W6 coalescing keys (``cooldown_ms``, ``digest_window_ms``; plan
  ``LENS_EXTENSIONS_2026-10-27.md`` §3 decision 1): an absent key is today's behaviour
  and is not emitted, so every manifest sealed before them keeps its canonical bytes
  and seal digest. The ``act`` level is out (ruling 3), so it is an unknown
  enum here, not a disabled option. The Work owner/scope/budget fields are cut.
* ``persona_id`` targets the forged turn. A DRAFT may leave it ``null``; a SEAL
  of an ``investigate`` monitor refuses ``null`` as ``persona_required``
  (:func:`check_sealable`; owner ruling 2026-10-19, plan p10-agent §5.2
  decision 1: hermes holds no Mission Control selection to default to).
  ``notify`` forges no turn and may keep ``null``.
* A money ``best_of`` compares PRODUCTS (W5): the seal refuses it unless every member
  carries ``product`` labels (``equivalence_unlabelled``, an ``unknown`` condition
  included) that agree on ``condition`` and case-folded ``variant``
  (``equivalence_mismatch``). Seal-only, so every revision sealed before it still reads;
  ``identity`` is not compared (marketplaces spell one product differently).

* ``schedule: {every_ms, offset_ms, brief}`` (OPTIONAL, plan
  ``planned/lens-deadline-schedule-equivalence-report-2026-10-27.md`` §2): a scheduled run every
  ``every_ms`` (15 min .. 7 d) at phase ``offset_ms`` (UTC), carrying the operator's standing ask
  ``brief``; absent is today's bytes. Refused ``schedule_needs_investigate`` on a ``notify``
  monitor, and ``schedule_over_cap`` when the cap would clip it every day (``schedules.py``
  produces the runs).

The schema is CLOSED at every level: a manifest with one unknown key is refused,
as is a missing key, a duplicate feed or rule id, a rule naming a feed the
manifest does not carry, and a document over 64 KiB canonical.
"""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Any

from .feed import ProductCondition, ValueKind, comparable_type, fx_feed_id, read_feed, value_type_of
from .rules import RuleForm, continuity_limit, read_rule, rule_feed_ids
from .wire_value import (
    MAXIMUM_MANIFEST_BYTES,
    WireError,
    WireRefusal,
    bounded_int,
    bounded_list,
    bounded_string,
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
#: W6: a rule's new Episode inside this long of its previous receipt is ``cooled`` (§3 decision 2).
MAXIMUM_COOLDOWN_MS = 24 * 60 * 60 * 1000
#: W6: the longest digest window — Episodes owed inside one share one turn (§3 decision 3).
MAXIMUM_DIGEST_WINDOW_MS = 6 * 60 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000
#: A scheduled run's shortest period: the :data:`MAXIMUM_DAILY_TURN_CAP` floor (one per quarter hour).
MINIMUM_SCHEDULE_EVERY_MS = DAY_MS // MAXIMUM_DAILY_TURN_CAP
MAXIMUM_SCHEDULE_EVERY_MS = 7 * DAY_MS
MAXIMUM_SCHEDULE_BRIEF_BYTES = 1024


class AutomationLevel(str, Enum):
    NOTIFY = "notify"
    INVESTIGATE = "investigate"


class AutomationWhen(str, Enum):
    URGENT = "urgent"
    ALWAYS = "always"


MANIFEST_KEYS = frozenset({"version", "monitor_id", "feeds", "rules", "automation", "persona_id"})
#: Optional top-level keys: read only when present, emitted only when present.
OPTIONAL_MANIFEST_KEYS = frozenset({"schedule"})
SCHEDULE_KEYS = frozenset({"every_ms", "offset_ms", "brief"})
AUTOMATION_KEYS = frozenset({"level", "when", "daily_turn_cap"})
#: Optional automation keys and their ceilings: read only when present, emitted only when present.
OPTIONAL_AUTOMATION_KEYS: dict[str, int] = {"cooldown_ms": MAXIMUM_COOLDOWN_MS,
                                            "digest_window_ms": MAXIMUM_DIGEST_WINDOW_MS}


def read_automation(value: Any) -> dict[str, Any]:
    m = checked_object(value, AUTOMATION_KEYS, OPTIONAL_AUTOMATION_KEYS)
    automation = {
        "level": enum_value(m["level"], AutomationLevel).value,
        "when": enum_value(m["when"], AutomationWhen).value,
        "daily_turn_cap": bounded_int(m["daily_turn_cap"], maximum=MAXIMUM_DAILY_TURN_CAP),
    }
    for key, maximum in OPTIONAL_AUTOMATION_KEYS.items():
        if key in m:
            automation[key] = bounded_int(m[key], maximum=maximum)
    return automation


def read_schedule(value: Any) -> dict[str, Any]:
    """``{every_ms, offset_ms, brief}``: interval plus UTC phase (``offset_ms`` < ``every_ms``)."""

    m = checked_object(value, SCHEDULE_KEYS)
    every = bounded_int(m["every_ms"], minimum=MINIMUM_SCHEDULE_EVERY_MS, maximum=MAXIMUM_SCHEDULE_EVERY_MS)
    return {"every_ms": every, "offset_ms": bounded_int(m["offset_ms"], maximum=every - 1),
            "brief": bounded_string(m["brief"], maximum=MAXIMUM_SCHEDULE_BRIEF_BYTES)}


def _check_schedule(manifest: dict[str, Any]) -> None:
    schedule, automation = manifest.get("schedule"), manifest["automation"]
    if schedule is None:
        return
    if automation["level"] != AutomationLevel.INVESTIGATE.value:
        raise WireError(WireRefusal.SCHEDULE_NEEDS_INVESTIGATE, "schedule")
    if -(-DAY_MS // schedule["every_ms"]) > automation["daily_turn_cap"]:
        raise WireError(WireRefusal.SCHEDULE_OVER_CAP, "schedule")


def read_manifest(value: Any) -> dict[str, Any]:
    """The canonical manifest dict, or :class:`WireError` naming the first refusal."""

    m = checked_object(value, MANIFEST_KEYS, OPTIONAL_MANIFEST_KEYS)
    manifest = {
        "version": bounded_int(m["version"], minimum=1, maximum=1),
        "monitor_id": opaque_id(m["monitor_id"]),
        "feeds": bounded_list(m["feeds"], read_feed, minimum=1, maximum=MAXIMUM_FEEDS),
        "rules": bounded_list(m["rules"], read_rule, maximum=MAXIMUM_RULES),
        "automation": read_automation(m["automation"]),
        "persona_id": optional(m["persona_id"], opaque_id),
    }
    if m.get("schedule") is not None:
        manifest["schedule"] = read_schedule(m["schedule"])
    feed_ids = [feed["id"] for feed in manifest["feeds"]]
    require(len(set(feed_ids)) == len(feed_ids), "duplicate feed id")
    rule_ids = [rule["id"] for rule in manifest["rules"]]
    require(len(set(rule_ids)) == len(rule_ids), "duplicate rule id")
    require(all(set(rule_feed_ids(rule)) <= set(feed_ids) for rule in manifest["rules"]), "rule names an unknown feed")
    _check_typed_rules(manifest)
    _check_schedule(manifest)
    if len(canonical_bytes(manifest)) > MAXIMUM_MANIFEST_BYTES:
        raise WireError(WireRefusal.OVER_BUDGET, "manifest byte budget")
    return manifest


#: The forms an instant feed admits: a deadline, the deadline moving, or the deadline going missing.
_INSTANT_FORMS = frozenset({RuleForm.ENDS_WITHIN, RuleForm.CHANGED, RuleForm.MOVED_BY, RuleForm.MISSING_DATA})


def _check_typed_rules(manifest: dict[str, Any]) -> None:
    """A comparison is only between like values; a deadline rule only reads an instant (W5, W7)."""

    types = {feed["id"]: value_type_of(feed) for feed in manifest["feeds"]}
    for feed in manifest["feeds"]:
        rate = fx_feed_id(feed)
        # The dated exchange rate is a plain-number feed of this same monitor (W5).
        require(rate is None or (rate in types and rate != feed["id"]
                                 and types[rate]["kind"] == ValueKind.NUMBER.value), "fx feed")
    comparable = {feed["id"]: comparable_type(feed) for feed in manifest["feeds"]}
    intervals = {feed["id"]: timedelta(milliseconds=feed["interval_ms"]) for feed in manifest["feeds"]}
    for rule in manifest["rules"]:
        form = RuleForm(rule["form"])
        # An absence shorter than one missed tick is jitter, not absence (§5 decision 1).
        require(form is not RuleForm.MISSING_DATA
                or timedelta(milliseconds=rule["window_ms"]) >= continuity_limit(intervals[rule["feed_id"]]),
                "missing_data window below the feed's continuity limit")
        if form is RuleForm.BEST_OF:
            # Totals in one currency compare; shipping, tax and source currency may differ (W5).
            group = [comparable[feed] for feed in rule_feed_ids(rule)]
            require(all(t == group[0] for t in group), "best_of group mixes value types")
            require(group[0]["kind"] != ValueKind.INSTANT.value, "best_of over instants")
        instant = types[rule["feed_id"]]["kind"] == ValueKind.INSTANT.value
        require(instant or form is not RuleForm.ENDS_WITHIN, "ends_within reads an instant feed")
        require(not instant or form in _INSTANT_FORMS, "an instant is compared by deadline or by change")


def check_sealable(manifest: dict[str, Any]) -> None:
    """What a seal adds to :func:`read_manifest`: an ``investigate`` monitor names its persona, and a
    money ``best_of`` compares one product (:func:`_check_equivalence`)."""

    if manifest["automation"]["level"] == AutomationLevel.INVESTIGATE.value and manifest["persona_id"] is None:
        raise WireError(WireRefusal.PERSONA_REQUIRED, "persona_id")
    _check_equivalence(manifest)


def money_best_of_members(manifest: dict[str, Any]) -> list[list[str]]:
    """Per money ``best_of`` rule, its member feed ids: the groups W5 says compare PRODUCTS.

    A ``best_of`` over plain numbers (latency across regions) is not a product comparison."""

    feeds = {feed["id"]: feed for feed in manifest["feeds"]}
    return [list(rule_feed_ids(rule)) for rule in manifest["rules"]
            if RuleForm(rule["form"]) is RuleForm.BEST_OF
            and value_type_of(feeds[rule_feed_ids(rule)[0]])["kind"] == ValueKind.MONEY.value]


def _check_equivalence(manifest: dict[str, Any]) -> None:
    """W5: every member of a money ``best_of`` is labelled, and all share condition and variant."""

    feeds = {feed["id"]: feed for feed in manifest["feeds"]}
    for group in money_best_of_members(manifest):
        products = [feeds[feed_id].get("product") for feed_id in group]
        if any(p is None or p["condition"] == ProductCondition.UNKNOWN.value for p in products):
            raise WireError(WireRefusal.EQUIVALENCE_UNLABELLED, "product")
        if len({(p["condition"], p["variant"].casefold()) for p in products}) > 1:
            raise WireError(WireRefusal.EQUIVALENCE_MISMATCH, "product")


def decode_manifest(source: str | bytes) -> dict[str, Any]:
    """Strict-decode then read: a duplicate key is refused before the dict forgets it."""

    return read_manifest(decode_strict_json(source, maximum_bytes=MAXIMUM_MANIFEST_BYTES))
