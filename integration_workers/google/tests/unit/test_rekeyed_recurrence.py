"""Unit tests for reconciling a recurrence whose instance ids Google re-keyed.

Re-timing a whole recurrence ("all events" at a new time) gives every
instance a new id - ``<recurrence>_<new start>`` - and Google never cancels
the old ids. Within the window Google returned, a journal linked to an id
Google no longer has is retired: adopted by the one new instance on its local
day, or cancelled when there is no unambiguous partner.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from calendar_models import GoogleEvent
from rekeyed_recurrence import (
    LiveInstances,
    RecurrenceLink,
    RetiredInstance,
    plan_rekeyed_instances,
)
from split_adoption import InstanceAdoption

SYDNEY = ZoneInfo("Australia/Sydney")
R = "dc7pp0jpb9fdfg6b6csu2jbfes"
OTHER = "0ur3d8ikbqrodfkpfne8pmro2l"

# 14:00 and 14:30 in Sydney (AEDT) on Mondays in December.
OLD_TIMES = [datetime(2026, 12, d, 3, 0, tzinfo=UTC) for d in (7, 14, 21)]
NEW_TIMES = [moment + timedelta(minutes=30) for moment in OLD_TIMES]
WINDOW_START = datetime(2026, 11, 1, tzinfo=UTC)
WINDOW_END = datetime(2027, 6, 1, tzinfo=UTC)


def _instance_id(moment: datetime, recurrence: str = R) -> str:
    return f"{recurrence}_{moment.strftime('%Y%m%dT%H%M%SZ')}"


def _live(
    moment: datetime, *, recurrence: str = R, summary: str = "Retro"
) -> GoogleEvent:
    data: dict[str, Any] = {
        "id": _instance_id(moment, recurrence),
        "status": "confirmed",
        "summary": summary,
        "recurringEventId": recurrence,
        "start": {"dateTime": moment.isoformat()},
        "end": {"dateTime": (moment + timedelta(hours=1)).isoformat()},
    }
    return GoogleEvent.from_api_response(data)


def _link(
    moment: datetime,
    journal_id: int,
    *,
    recurrence: str | None = R,
    sync_capability: str = "bidirectional",
    external_event_id: str | None = None,
) -> RecurrenceLink:
    return RecurrenceLink(
        external_event_id=external_event_id
        or _instance_id(moment, recurrence or "legacy"),
        recurring_event_id=recurrence,
        journal_id=journal_id,
        start=moment,
        sync_capability=sync_capability,
    )


def _google_has(
    *moments: datetime,
    recurrence: str = R,
    window_start: datetime = WINDOW_START,
    window_end: datetime = WINDOW_END,
) -> dict[str, LiveInstances]:
    return {
        recurrence: LiveInstances(
            event_ids=frozenset(_instance_id(m, recurrence) for m in moments),
            window_start=window_start,
            window_end=window_end,
        )
    }


def test_a_same_day_re_time_adopts_every_old_journal() -> None:
    events = [_live(moment) for moment in NEW_TIMES]
    links = [_link(moment, 100 + i) for i, moment in enumerate(OLD_TIMES)]

    plan = plan_rekeyed_instances(events, links, _google_has(*NEW_TIMES), SYDNEY)

    assert plan.targets == {
        _instance_id(new): InstanceAdoption(
            journal_id=100 + i,
            old_event_id=_instance_id(old),
            adopted_from=None,
            rekeyed=True,
        )
        for i, (old, new) in enumerate(zip(OLD_TIMES, NEW_TIMES, strict=True))
    }
    assert plan.retired == tuple(
        RetiredInstance(
            external_event_id=_instance_id(old),
            recurring_event_id=R,
            journal_id=100 + i,
        )
        for i, old in enumerate(OLD_TIMES)
    )


def test_a_rename_with_the_re_time_still_adopts() -> None:
    events = [_live(NEW_TIMES[0], summary="Sprint close + retro - NYX")]
    links = [_link(OLD_TIMES[0], 100)]

    plan = plan_rekeyed_instances(events, links, _google_has(NEW_TIMES[0]), SYDNEY)

    assert plan.targets[_instance_id(NEW_TIMES[0])].journal_id == 100


def test_a_move_to_another_day_cancels_the_old_and_creates_the_new() -> None:
    tuesday = OLD_TIMES[0] + timedelta(days=1)
    events = [_live(tuesday)]
    links = [_link(OLD_TIMES[0], 100)]

    plan = plan_rekeyed_instances(events, links, _google_has(tuesday), SYDNEY)

    assert plan.targets == {}
    assert [r.journal_id for r in plan.retired] == [100]


def test_two_candidates_on_one_day_pair_nothing_but_still_retire() -> None:
    morning, afternoon = OLD_TIMES[0] - timedelta(hours=2), OLD_TIMES[0]
    new_morning, new_afternoon = (
        morning + timedelta(minutes=30),
        afternoon + timedelta(minutes=30),
    )
    events = [_live(new_morning), _live(new_afternoon)]
    links = [_link(morning, 100), _link(afternoon, 101)]

    plan = plan_rekeyed_instances(
        events, links, _google_has(new_morning, new_afternoon), SYDNEY
    )

    assert plan.targets == {}
    assert sorted(r.journal_id for r in plan.retired) == [100, 101]


def test_an_instance_google_still_has_is_left_alone() -> None:
    events = [_live(NEW_TIMES[1])]
    links = [_link(OLD_TIMES[0], 100)]

    plan = plan_rekeyed_instances(
        events, links, _google_has(OLD_TIMES[0], NEW_TIMES[1]), SYDNEY
    )

    assert plan.targets == {}
    assert plan.retired == ()


def test_an_instance_cancelled_in_the_batch_is_left_to_its_cancellation() -> None:
    cancelled = GoogleEvent.from_api_response(
        {
            "id": _instance_id(OLD_TIMES[0]),
            "status": "cancelled",
            "recurringEventId": R,
        }
    )
    events = [cancelled, _live(NEW_TIMES[0])]
    links = [_link(OLD_TIMES[0], 100)]

    plan = plan_rekeyed_instances(events, links, _google_has(NEW_TIMES[0]), SYDNEY)

    assert plan.targets == {}
    assert plan.retired == ()


def test_links_outside_the_window_google_returned_are_never_retired() -> None:
    # Google stops expanding an endless recurrence after a fixed number of
    # instances, so a link past the last one it returned may still be live.
    before = WINDOW_START - timedelta(days=7)
    after = WINDOW_END + timedelta(days=7)
    links = [_link(before, 100), _link(after, 101)]

    plan = plan_rekeyed_instances(
        [_live(NEW_TIMES[0])], links, _google_has(NEW_TIMES[0]), SYDNEY
    )

    assert plan.retired == ()


def test_links_google_did_not_list_for_are_ignored() -> None:
    links = [
        _link(OLD_TIMES[0], 100, recurrence=OTHER),
        _link(OLD_TIMES[1], 101, sync_capability="outbound"),
        _link(OLD_TIMES[2], 102, recurrence=None),
    ]
    events = [_live(moment) for moment in NEW_TIMES]

    plan = plan_rekeyed_instances(events, links, _google_has(*NEW_TIMES), SYDNEY)

    assert plan.targets == {}
    assert plan.retired == ()


def test_a_new_instance_already_linked_is_not_a_candidate() -> None:
    # A legacy link (no recurring id recorded) still links the instance.
    events = [_live(NEW_TIMES[0])]
    links = [
        _link(OLD_TIMES[0], 100),
        _link(
            NEW_TIMES[0],
            200,
            recurrence=None,
            external_event_id=_instance_id(NEW_TIMES[0]),
        ),
    ]

    plan = plan_rekeyed_instances(events, links, _google_has(NEW_TIMES[0]), SYDNEY)

    assert plan.targets == {}
    assert [r.journal_id for r in plan.retired] == [100]


def test_days_are_read_in_the_users_zone() -> None:
    # 23:30 Monday and 00:30 Tuesday in Sydney share a UTC day, not a local one.
    old = datetime(2026, 12, 7, 12, 30, tzinfo=UTC)  # 23:30 Mon AEDT
    new = datetime(2026, 12, 7, 13, 30, tzinfo=UTC)  # 00:30 Tue AEDT

    plan = plan_rekeyed_instances(
        [_live(new)], [_link(old, 100)], _google_has(new), SYDNEY
    )

    assert plan.targets == {}
    assert [r.journal_id for r in plan.retired] == [100]
