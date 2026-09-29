import pytest

from gateway import hosted_room_driver as driver
from tests.gateway.test_hosted_room_driver import FakeClock, _identity, _lease, _payload, db


def admit(path, clock, key, member, *, source=1, independent=True):
    identity = _identity(key, turn_id=key)
    payload = _payload(target_member_id=member, source_event_seq=source)
    if independent:
        payload["independent"] = True
    driver.admit_task(path, identity, payload=payload, clock=clock)
    return identity


def start(path, clock, lease, identity):
    return driver.start_task(path, identity, lease, expected_cancel_generation=0, clock=clock)


def test_batch_overlaps_members_but_checks_every_active_member(db):
    clock = FakeClock()
    lease = _lease(db, clock)
    one = admit(db, clock, "first", "a")
    start(db, clock, lease, one)
    two = admit(db, clock, "second", "b")
    start(db, clock, lease, two)
    # A LIMIT 1 check would overlook the second member's existing execution.
    duplicate = admit(db, clock, "third", "b")
    with pytest.raises(driver.InvalidTaskTransitionError):
        start(db, clock, lease, duplicate)


@pytest.mark.parametrize("source,independent", [(2, True), (1, False)])
def test_different_message_or_sequential_work_cannot_overlap(db, source, independent):
    clock = FakeClock()
    lease = _lease(db, clock)
    start(db, clock, lease, admit(db, clock, "first", "a"))
    other = admit(db, clock, "second", "b", source=source, independent=independent)
    with pytest.raises(driver.InvalidTaskTransitionError):
        start(db, clock, lease, other)


def test_opt_in_does_not_bypass_an_ordinary_discussion(db):
    clock = FakeClock()
    lease = _lease(db, clock)
    start(db, clock, lease, admit(db, clock, "first", "a", independent=False))
    comparison = admit(db, clock, "second", "b")
    with pytest.raises(driver.InvalidTaskTransitionError):
        start(db, clock, lease, comparison)
