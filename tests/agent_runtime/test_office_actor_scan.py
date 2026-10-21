"""``ActorScan.with_written`` — the upsert's one scan, carried past its own write
(RT-OFFICE-PATCH-LANE-SCANS-EVERY-UPSERT, stage S1).

Pure: no store, no disk. KILLING MUTATION: drop the replace arm (keep every row
of ``self.actors``) -> "a replace keeps the count" reds at count + 1.
"""

from __future__ import annotations

from agent_runtime.models import OfficeActor
from agent_runtime.office_store.models import ActorScan, UnreadableActorFiles


def _actor(key: str, *, revision: int = 1) -> OfficeActor:
    return OfficeActor(actor_key=key, workspace_id="ws", persona_id=key, revision=revision)


def test_a_replace_keeps_the_count_and_carries_the_written_row():
    scan = ActorScan([_actor("a"), _actor("b"), _actor("c")])

    after = scan.with_written(_actor("b", revision=2))

    assert len(after.actors) == 3
    assert [(row.actor_key, row.revision) for row in after.actors] == [("a", 1), ("b", 2), ("c", 1)]


def test_an_append_raises_the_count_by_one_in_key_order():
    scan = ActorScan([_actor("a"), _actor("c")])

    after = scan.with_written(_actor("b"))

    assert [row.actor_key for row in after.actors] == ["a", "b", "c"]
    assert [row.actor_key for row in scan.actors] == ["a", "c"], "the source scan was mutated"


def test_the_unreadable_files_ride_unchanged():
    unreadable = UnreadableActorFiles(names=("broken.json",), total=1)
    scan = ActorScan([_actor("a")], unreadable)

    after = scan.with_written(_actor("z"))

    assert after.unreadable_files is unreadable
    assert after.unreadable == 1
