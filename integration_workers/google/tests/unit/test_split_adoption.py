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
    end: datetime | None = None,
    title: str = "Pilates",
    sync_capability: str = "bidirectional",
    displayed_here: bool = True,
) -> tuple[str, LinkedInstance]:
    external_event_id = f"{OLD}_{instance}"
    return external_event_id, LinkedInstance(
        external_event_id=external_event_id,
        journal_id=journal_id,
        title=title,
        start=start,
        end=end or start + timedelta(minutes=75),
        sync_capability=sync_capability,
        displayed_here=displayed_here,
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
            f"{NEW}_{NEW_START}": SplitTarget(
                journal_id=224578,
                adopted_from=OLD,
                old_event_id=f"{OLD}_20261016T011000Z",
            )
        }

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
            end=OLD_START,
            sync_capability="bidirectional",
            displayed_here=True,
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
                end=OLD_START,
                sync_capability="bidirectional",
                displayed_here=True,
            )
        }

        [target] = pair_split_instances(events, links, SYDNEY, NOW).targets.values()

        assert target == SplitTarget(
            journal_id=7,
            adopted_from=OLD,
            old_event_id=f"{old_split}_20261016T011000Z",
        )

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
            new_event.id: SplitTarget(
                journal_id=3, adopted_from=OLD, old_event_id=f"{OLD}_20261016"
            )
        }

    def test_an_offset_free_time_is_read_in_the_events_own_zone(self) -> None:
        """Google may send a bare local time with ``start.timeZone``: 22:00 on
        the 16th in Sydney, not 22:00 UTC (the 17th in Sydney)."""
        old_start = datetime(2026, 10, 16, 11, 10, tzinfo=UTC)  # 22:10 Sydney
        new_event = GoogleEvent.from_api_response(
            {
                "id": f"{NEW}_bare",
                "status": "confirmed",
                "summary": "Pilates",
                "start": {
                    "dateTime": "2026-10-16T22:00:00",
                    "timeZone": "Australia/Sydney",
                },
                "end": {
                    "dateTime": "2026-10-16T23:00:00",
                    "timeZone": "Australia/Sydney",
                },
                "recurringEventId": NEW,
            }
        )
        events = [_cancelled("20261016T111000Z"), new_event]
        links = dict([_link("20261016T111000Z", 5, old_start)])

        assert pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_an_occurrence_still_under_way_is_eligible(self) -> None:
        """Eligibility follows the sync's past-cancellation skip, which reads
        the end: a multi-day occurrence that began days ago is not over."""
        began = NOW - timedelta(days=3)
        events = [
            _cancelled("multiday"),
            _live(began.astimezone(SYDNEY).isoformat()),
        ]
        links = dict([_link("multiday", 6, began, end=NOW + timedelta(days=1))])

        assert pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_an_unparseable_start_pairs_nothing_and_raises_nothing(self) -> None:
        """A malformed event is the sync loop's to reject, one event at a time;
        the pairing pass runs before that boundary, so it must not throw."""
        events = [
            _cancelled("20261016T011000Z"),
            GoogleEvent.from_api_response(
                {
                    "id": f"{NEW}_bad",
                    "status": "confirmed",
                    "summary": "Pilates",
                    "start": {"dateTime": "not-a-time"},
                    "recurringEventId": NEW,
                }
            ),
            GoogleEvent.from_api_response(
                {
                    "id": f"{NEW}_bad_date",
                    "status": "confirmed",
                    "summary": "Pilates",
                    "start": {"date": "16/10/2026"},
                    "recurringEventId": NEW,
                }
            ),
        ]
        links = dict([_link("20261016T011000Z", 1, OLD_START)])

        assert not pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_a_cancelled_copy_shown_in_another_calendar_does_not_pair(self) -> None:
        """Its series is keyed on the calendar it is displayed in."""
        events = [_cancelled("20261016T011000Z"), _live(NEW_START)]
        links = dict([_link("20261016T011000Z", 1, OLD_START, displayed_here=False)])

        assert not pair_split_instances(events, links, SYDNEY, NOW).targets

    def test_a_live_shared_copy_is_still_journalled_not_a_new_candidate(
        self,
    ) -> None:
        """A live event linked here, though displayed elsewhere, is already
        journalled: it must not count as a second new instance that day."""
        shared = _live("2026-10-16T18:00:00+11:00", event_id="shared-copy")
        events = [_cancelled("20261016T011000Z"), _live(NEW_START), shared]
        links = dict([_link("20261016T011000Z", 1, OLD_START)])
        links[shared.id] = LinkedInstance(
            external_event_id=shared.id,
            journal_id=9,
            title="Pilates",
            start=OLD_START,
            end=OLD_START,
            sync_capability="bidirectional",
            displayed_here=False,
        )

        assert pair_split_instances(events, links, SYDNEY, NOW).targets
