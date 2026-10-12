"""Unit tests for pairing the two halves of a split recurrence in one sync.

A "this and following" edit can end the old recurrence and start a new one
under an unrelated id. Within one sync batch that shows up as a cancelled
instance of the old recurrence and a new instance of another one on the same
day, under the same title. Pairing them lets the old journal be updated in
place instead of cancelled while a duplicate is created.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from calendar_models import GoogleEvent
from split_adoption import (
    LinkedInstance,
    SplitTarget,
    pair_split_instances,
)

SYDNEY = ZoneInfo("Australia/Sydney")
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
OLD = "63goti53s6ji2dtl4qapbbmr6q"
NEW = "9p7kac2r5m992mshlenq0j10pf"


def _cancelled(instance: str, recurring_event_id: str = OLD) -> GoogleEvent:
    """A cancelled instance as Google sends it: no summary, no start."""
    return GoogleEvent.from_api_response(
        {
            "id": f"{recurring_event_id}_{instance}",
            "status": "cancelled",
            "recurringEventId": recurring_event_id,
        }
    )


def _live(
    start: str,
    *,
    summary: str = "Pilates",
    recurring_event_id: str | None = NEW,
    event_id: str | None = None,
) -> GoogleEvent:
    data: dict[str, Any] = {
        "id": event_id or f"{recurring_event_id}_{start}",
        "status": "confirmed",
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": start},
    }
    if recurring_event_id is not None:
        data["recurringEventId"] = recurring_event_id
    return GoogleEvent.from_api_response(data)


def _link(
    instance: str,
    journal_id: int,
    start: datetime,
    *,
    title: str = "Pilates",
    sync_capability: str = "bidirectional",
) -> tuple[str, LinkedInstance]:
    external_event_id = f"{OLD}_{instance}"
    return external_event_id, LinkedInstance(
        external_event_id=external_event_id,
        journal_id=journal_id,
        title=title,
        start=start,
        sync_capability=sync_capability,
    )


# 16 Oct 12:10 in Sydney (AEDT) is 01:10 UTC; the new series starts at 12:20.
OLD_START = datetime(2026, 10, 16, 1, 10, tzinfo=UTC)
NEW_START = "2026-10-16T12:20:00+11:00"


class TestPairSplitInstances:
    def test_a_cancelled_old_instance_pairs_with_the_new_one_that_day(self) -> None:
        events = [_cancelled("20261016T011000Z"), _live(NEW_START)]
        links = dict([_link("20261016T011000Z", 224578, OLD_START)])

        pairing = pair_split_instances(events, links, SYDNEY, NOW)

        assert pairing.targets == {
            f"{NEW}_{NEW_START}": SplitTarget(journal_id=224578, adopted_from=OLD)
        }
        assert pairing.skip_ids == frozenset({f"{OLD}_20261016T011000Z"})

    def test_titles_match_ignoring_case_and_surrounding_space(self) -> None:
        events = [_cancelled("20261016T011000Z"), _live(NEW_START, summary=" pilates ")]
        links = dict([_link("20261016T011000Z", 1, OLD_START)])

        assert pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_the_day_is_the_local_day(self) -> None:
        """10:50 and 11:10 on the 16th in Sydney straddle UTC midnight: the
        same local day, but the 15th and the 16th in UTC."""
        old_start = datetime(2026, 10, 15, 23, 50, tzinfo=UTC)
        events = [
            _cancelled("20261015T235000Z"),
            _live("2026-10-16T11:10:00+11:00"),
        ]
        links = dict([_link("20261015T235000Z", 1, old_start)])

        assert pair_split_instances(events, links, SYDNEY, NOW).targets
        assert not pair_split_instances(events, links, ZoneInfo("UTC"), NOW).targets

    def test_a_different_title_does_not_pair(self) -> None:
        events = [_cancelled("20261016T011000Z"), _live(NEW_START, summary="Yoga")]
        links = dict([_link("20261016T011000Z", 1, OLD_START)])

        pairing = pair_split_instances(events, links, SYDNEY, NOW)

        assert not pairing.targets
        assert not pairing.skip_ids

    def test_a_different_day_does_not_pair(self) -> None:
        events = [_cancelled("20261016T011000Z"), _live("2026-10-17T12:20:00+11:00")]
        links = dict([_link("20261016T011000Z", 1, OLD_START)])

        assert not pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_two_candidates_on_either_side_do_not_pair(self) -> None:
        """A wrong merge is worse than a duplicate: ambiguity pairs nothing."""
        events = [
            _cancelled("20261016T011000Z"),
            _live(NEW_START),
            _live("2026-10-16T18:00:00+11:00"),
        ]
        links = dict([_link("20261016T011000Z", 1, OLD_START)])

        assert not pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_the_same_recurrence_does_not_pair(self) -> None:
        events = [
            _cancelled("20261016T011000Z"),
            _live(NEW_START, recurring_event_id=OLD, event_id="moved"),
        ]
        links = dict([_link("20261016T011000Z", 1, OLD_START)])

        assert not pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_a_single_new_event_does_not_pair(self) -> None:
        """Only an instance of another recurrence is a split's other half."""
        events = [
            _cancelled("20261016T011000Z"),
            _live(NEW_START, recurring_event_id=None, event_id="one-off"),
        ]
        links = dict([_link("20261016T011000Z", 1, OLD_START)])

        assert not pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_an_already_linked_new_event_does_not_pair(self) -> None:
        new_event = _live(NEW_START)
        events = [_cancelled("20261016T011000Z"), new_event]
        links = dict([_link("20261016T011000Z", 1, OLD_START)])
        links[new_event.id] = LinkedInstance(
            external_event_id=new_event.id,
            journal_id=2,
            title="Pilates",
            start=OLD_START,
            sync_capability="bidirectional",
        )

        assert not pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_an_outbound_only_link_does_not_pair(self) -> None:
        """Inbound changes never reach a journal synced one way out."""
        events = [_cancelled("20261016T011000Z"), _live(NEW_START)]
        links = dict(
            [_link("20261016T011000Z", 1, OLD_START, sync_capability="outbound")]
        )

        assert not pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_an_unlinked_cancellation_does_not_pair(self) -> None:
        events = [_cancelled("20261016T011000Z"), _live(NEW_START)]

        assert not pair_split_instances(events, {}, SYDNEY, NOW).targets

    def test_a_past_old_instance_does_not_pair(self) -> None:
        """Past cancellations are skipped by the sync, so are not split halves."""
        past = NOW - timedelta(days=3)
        events = [
            _cancelled("20261005T011000Z"),
            _live(past.astimezone(SYDNEY).isoformat()),
        ]
        links = dict([_link("20261005T011000Z", 1, past)])

        assert not pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_a_split_of_a_split_adopts_into_the_root_series(self) -> None:
        old_split = f"{OLD}_R20260801T011000"
        events = [
            _cancelled("20261016T011000Z", recurring_event_id=old_split),
            _live(NEW_START),
        ]
        external_event_id = f"{old_split}_20261016T011000Z"
        links = {
            external_event_id: LinkedInstance(
                external_event_id=external_event_id,
                journal_id=7,
                title="Pilates",
                start=OLD_START,
                sync_capability="bidirectional",
            )
        }

        [target] = pair_split_instances(events, links, SYDNEY, NOW).targets.values()

        assert target == SplitTarget(journal_id=7, adopted_from=OLD)

    def test_an_all_day_split_pairs_on_its_date(self) -> None:
        old_start = datetime(2026, 10, 15, 13, 0, tzinfo=UTC)  # 16 Oct, local midnight
        new_event = GoogleEvent.from_api_response(
            {
                "id": f"{NEW}_20261016",
                "status": "confirmed",
                "summary": "Pilates",
                "start": {"date": "2026-10-16"},
                "end": {"date": "2026-10-17"},
                "recurringEventId": NEW,
            }
        )
        events = [_cancelled("20261016"), new_event]
        links = dict([_link("20261016", 3, old_start)])

        assert pair_split_instances(events, links, SYDNEY, NOW).targets == {
            new_event.id: SplitTarget(journal_id=3, adopted_from=OLD)
        }
