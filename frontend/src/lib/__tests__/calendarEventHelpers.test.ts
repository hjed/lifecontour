import {
  toCalendarEvent,
  toCalendarEvents,
  groupEventsByDate,
  getMonthDateRange,
  getAgendaDateRange,
  getWeekDateRange,
  getDayDateRange,
  CalendarEvent,
} from '../calendarEventHelpers';
import { DisplayJournal } from '@/utils/journalTransformers';
import { JournalType, EventState } from '@/types/journals';

const createMockDisplayJournal = (
  overrides: Partial<DisplayJournal> = {}
): DisplayJournal => ({
  id: '1',
  title: 'Test Journal',
  content: 'Some content',
  event_date_range: {
    start: '2026-04-15T10:00:00',
    end: '2026-04-15T11:00:00',
  },
  types: [JournalType.EVENT],
  tags: [],
  contacts: [],
  calendar: {
    id: 'cal-1',
    name: 'Personal',
    color: '#3b82f6',
  },
  type_data: {
    event: {
      calendar_id: 'cal-1',
      start_time: '10:00:00',
      end_time: '11:00:00',
      is_all_day: false,
      sync_invitees: false,
    },
  },
  ...overrides,
});

describe('calendarEventHelpers', () => {
  describe('toCalendarEvent', () => {
    it('extracts correct fields from a DisplayJournal', () => {
      const journal = createMockDisplayJournal();
      const event = toCalendarEvent(journal);

      expect(event.id).toBe('1');
      expect(event.title).toBe('Test Journal');
      expect(event.date).toBe('2026-04-15');
      expect(event.startTime).toBe('10:00');
      expect(event.endTime).toBe('11:00');
      expect(event.isAllDay).toBe(false);
      expect(event.calendarColor).toBe('#3b82f6');
      expect(event.calendarName).toBe('Personal');
      expect(event.isCancelled).toBe(false);
      expect(event.journalTypes).toEqual([JournalType.EVENT]);
      expect(event.hasPendingReviews).toBe(false);
    });

    it('handles journal without calendar (default colour)', () => {
      const journal = createMockDisplayJournal({
        calendar: null,
      });
      const event = toCalendarEvent(journal);

      expect(event.calendarColor).toBe('#6b7280');
      expect(event.calendarName).toBeUndefined();
    });

    it('handles all-day events (no start/end time)', () => {
      const journal = createMockDisplayJournal({
        type_data: {
          event: {
            calendar_id: 'cal-1',
            start_time: null,
            end_time: null,
            is_all_day: true,
            sync_invitees: false,
          },
        },
      });
      const event = toCalendarEvent(journal);

      expect(event.isAllDay).toBe(true);
      expect(event.startTime).toBeNull();
      expect(event.endTime).toBeNull();
    });

    it('handles cancelled event state', () => {
      const journal = createMockDisplayJournal({
        type_data: {
          event: {
            calendar_id: 'cal-1',
            start_time: '10:00:00',
            end_time: '11:00:00',
            is_all_day: false,
            sync_invitees: false,
            event_state: EventState.CANCELLED,
          },
        },
      });
      const event = toCalendarEvent(journal);

      expect(event.isCancelled).toBe(true);
      expect(event.eventState).toBe(EventState.CANCELLED);
    });

    it('handles journal without event type data', () => {
      const journal = createMockDisplayJournal({
        types: [JournalType.NOTE],
        type_data: {},
      });
      const event = toCalendarEvent(journal);

      expect(event.isAllDay).toBe(true);
      expect(event.startTime).toBeNull();
      expect(event.endTime).toBeNull();
    });

    it('propagates has_pending_reviews flag', () => {
      const journal = createMockDisplayJournal({
        has_pending_reviews: true,
      });
      const event = toCalendarEvent(journal);

      expect(event.hasPendingReviews).toBe(true);
    });
  });

  describe('toCalendarEvents', () => {
    it('converts an array of DisplayJournals to CalendarEvents', () => {
      const journals = [
        createMockDisplayJournal({ id: '1', title: 'First' }),
        createMockDisplayJournal({ id: '2', title: 'Second' }),
      ];

      const events = toCalendarEvents(journals);
      expect(events).toHaveLength(2);
      expect(events[0].id).toBe('1');
      expect(events[1].id).toBe('2');
    });

    it('returns empty array for empty input', () => {
      expect(toCalendarEvents([])).toEqual([]);
    });
  });

  describe('groupEventsByDate', () => {
    it('groups events into correct date buckets', () => {
      const events: CalendarEvent[] = [
        {
          id: '1',
          title: 'Event A',
          date: '2026-04-15',
          endDate: '2026-04-15',
          isMultiDay: false,
          startTime: '10:00',
          endTime: '11:00',
          isAllDay: false,
          calendarColor: '#3b82f6',
          isCancelled: false,
          journalTypes: [JournalType.EVENT],
          hasPendingReviews: false,
          isSyncedToGoogle: false,
        },
        {
          id: '2',
          title: 'Event B',
          date: '2026-04-15',
          endDate: '2026-04-15',
          isMultiDay: false,
          startTime: '14:00',
          endTime: '15:00',
          isAllDay: false,
          calendarColor: '#ef4444',
          isCancelled: false,
          journalTypes: [JournalType.EVENT],
          hasPendingReviews: false,
          isSyncedToGoogle: false,
        },
        {
          id: '3',
          title: 'Event C',
          date: '2026-04-16',
          endDate: '2026-04-16',
          isMultiDay: false,
          startTime: null,
          endTime: null,
          isAllDay: true,
          calendarColor: '#3b82f6',
          isCancelled: false,
          journalTypes: [JournalType.EVENT],
          hasPendingReviews: false,
          isSyncedToGoogle: false,
        },
      ];

      const grouped = groupEventsByDate(events);
      expect(Object.keys(grouped)).toHaveLength(2);
      expect(grouped['2026-04-15']).toHaveLength(2);
      expect(grouped['2026-04-16']).toHaveLength(1);
    });

    it('returns empty object for empty input', () => {
      expect(groupEventsByDate([])).toEqual({});
    });
  });

  describe('getMonthDateRange', () => {
    it('returns grid boundaries including adjacent months for April 2026', () => {
      const range = getMonthDateRange(2026, 3); // 0-indexed month
      expect(range.start).toBe('2026-03-30');
      expect(range.end).toBe('2026-05-03');
    });

    it('returns grid boundaries including previous year for January', () => {
      const range = getMonthDateRange(2026, 0);
      expect(range.start).toBe('2025-12-29');
      expect(range.end).toBe('2026-02-01');
    });

    it('handles February in a leap year', () => {
      const range = getMonthDateRange(2028, 1); // 2028 is a leap year
      expect(range.start).toBe('2028-01-31');
      expect(range.end).toBe('2028-03-05');
    });

    it('handles February in a non-leap year', () => {
      const range = getMonthDateRange(2026, 1);
      expect(range.start).toBe('2026-01-26');
      expect(range.end).toBe('2026-03-01');
    });

    it('handles December spilling into next year', () => {
      const range = getMonthDateRange(2026, 11);
      expect(range.start).toBe('2026-11-30');
      expect(range.end).toBe('2027-01-03');
    });
  });

  describe('getAgendaDateRange', () => {
    it('returns correct range from anchor with defaults', () => {
      const anchor = new Date(2026, 3, 15); // April 15, 2026
      const range = getAgendaDateRange(anchor, 30, 14);
      expect(range.start).toBe('2026-04-01');
      expect(range.end).toBe('2026-05-15');
    });

    it('handles start of year', () => {
      const anchor = new Date(2026, 0, 5); // January 5, 2026
      const range = getAgendaDateRange(anchor, 30, 14);
      expect(range.start).toBe('2025-12-22');
      expect(range.end).toBe('2026-02-04');
    });
  });

  describe('getWeekDateRange', () => {
    it('returns Monday to Sunday for a given date', () => {
      const date = new Date(2026, 3, 15); // April 15, 2026 (Wednesday)
      const range = getWeekDateRange(date);
      expect(range.start).toBe('2026-04-13'); // Monday
      expect(range.end).toBe('2026-04-19'); // Sunday
    });

    it('handles a date that falls on a Sunday', () => {
      const date = new Date(2026, 3, 19); // April 19, 2026 (Sunday)
      const range = getWeekDateRange(date);
      // It should still return the Monday of that exact week
      expect(range.start).toBe('2026-04-13'); // Monday
      expect(range.end).toBe('2026-04-19'); // Sunday
    });
  });

  describe('getDayDateRange', () => {
    it('returns the same start and end day', () => {
      const date = new Date(2026, 3, 15); // April 15, 2026
      const range = getDayDateRange(date);
      expect(range.start).toBe('2026-04-15');
      expect(range.end).toBe('2026-04-15');
    });
  });

  describe('multiday events', () => {
    it('toCalendarEvent sets endDate and isMultiDay for multiday events', () => {
      const journal = createMockDisplayJournal({
        event_date_range: {
          start: '2026-04-15T00:00:00',
          end: '2026-04-17T23:59:59',
        },
        type_data: {
          event: {
            calendar_id: 'cal-1',
            start_time: null,
            end_time: null,
            is_all_day: true,
            sync_invitees: false,
          },
        },
      });
      const event = toCalendarEvent(journal);

      expect(event.date).toBe('2026-04-15');
      expect(event.endDate).toBe('2026-04-17');
      expect(event.isMultiDay).toBe(true);
    });

    it('toCalendarEvent marks single-day events as not multiday', () => {
      const journal = createMockDisplayJournal();
      const event = toCalendarEvent(journal);

      expect(event.date).toBe('2026-04-15');
      expect(event.endDate).toBe('2026-04-15');
      expect(event.isMultiDay).toBe(false);
    });

    it('groupEventsByDate places multiday events in every day bucket', () => {
      const multidayEvent: CalendarEvent = {
        id: '10',
        title: 'Conference',
        date: '2026-04-15',
        endDate: '2026-04-17',
        isMultiDay: true,
        startTime: null,
        endTime: null,
        isAllDay: true,
        calendarColor: '#3b82f6',
        isCancelled: false,
        journalTypes: [JournalType.EVENT],
        hasPendingReviews: false,
        isSyncedToGoogle: false,
      };

      const grouped = groupEventsByDate([multidayEvent]);
      expect(Object.keys(grouped).sort()).toEqual([
        '2026-04-15',
        '2026-04-16',
        '2026-04-17',
      ]);
      // Same event should appear in each bucket
      expect(grouped['2026-04-15'][0].id).toBe('10');
      expect(grouped['2026-04-16'][0].id).toBe('10');
      expect(grouped['2026-04-17'][0].id).toBe('10');
    });

    it('groupEventsByDate handles mix of single and multiday events', () => {
      const singleEvent: CalendarEvent = {
        id: '1',
        title: 'Meeting',
        date: '2026-04-15',
        endDate: '2026-04-15',
        isMultiDay: false,
        startTime: '10:00',
        endTime: '11:00',
        isAllDay: false,
        calendarColor: '#ef4444',
        isCancelled: false,
        journalTypes: [JournalType.EVENT],
        hasPendingReviews: false,
        isSyncedToGoogle: false,
      };

      const multidayEvent: CalendarEvent = {
        id: '2',
        title: 'Trip',
        date: '2026-04-15',
        endDate: '2026-04-16',
        isMultiDay: true,
        startTime: null,
        endTime: null,
        isAllDay: true,
        calendarColor: '#3b82f6',
        isCancelled: false,
        journalTypes: [JournalType.EVENT],
        hasPendingReviews: false,
        isSyncedToGoogle: false,
      };

      const grouped = groupEventsByDate([singleEvent, multidayEvent]);
      // April 15 should have both events
      expect(grouped['2026-04-15']).toHaveLength(2);
      // April 16 should only have the multiday event
      expect(grouped['2026-04-16']).toHaveLength(1);
      expect(grouped['2026-04-16'][0].id).toBe('2');
    });
  });
});
