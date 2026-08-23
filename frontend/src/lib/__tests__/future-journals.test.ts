/**
 * Tests for the future-journal option list the retarget picker is built on.
 *
 * Pure, and deliberately so. Two rules live here that a rendered test could
 * only assert vaguely:
 *
 * - **Strictly after today**, mirroring the backend's `is_future_dated`. Today
 *   is not the future, so a journal starting later the same local day is not
 *   an eligible due journal and must not be offered as one.
 * - **Nearest first**, which the list endpoint cannot be asked for: it answers
 *   `ORDER BY event_date_range_start DESC` and takes no `sort` parameter, so
 *   the ordering the specification asks for is assembled here.
 *
 * The timezone is a parameter rather than the browser's, because the rule the
 * server applies is anchored on the user's *configured* zone.
 */

import {
  addDaysToIsoDate,
  formatFutureJournalDate,
  futureJournalOptions,
  localDateIn,
  todayIn,
} from '@/lib/future-journals';
import { formatIsoDate } from '@/lib/date-utils';
import { EventState, JournalType } from '@/types/journals';
import type { JournalResource } from '@/types/journals';

const SYDNEY = 'Australia/Sydney';

function journal(
  id: string,
  start: string,
  overrides: Partial<JournalResource['attributes']> = {}
): JournalResource {
  return {
    id,
    type: 'journals',
    attributes: {
      title: `Journal ${id}`,
      content: '',
      event_date_range: { start, end: start },
      types: [JournalType.NOTE],
      contacts: [],
      tags: [],
      ...overrides,
    },
  };
}

function cancelledEvent(id: string, start: string): JournalResource {
  return journal(id, start, {
    types: [JournalType.EVENT],
    type_data: {
      [JournalType.EVENT]: {
        calendar_id: 'cal-1',
        is_all_day: true,
        sync_invitees: false,
        private_description: false,
        event_state: EventState.CANCELLED,
      },
    },
  });
}

describe('localDateIn', () => {
  it('reads an instant as the calendar date it falls on in the given zone', () => {
    // 14:00 UTC on the 23rd is already midnight on the 24th in Sydney.
    expect(localDateIn(SYDNEY, '2026-08-23T14:00:00Z')).toBe('2026-08-24');
    expect(localDateIn('UTC', '2026-08-23T14:00:00Z')).toBe('2026-08-23');
  });

  it('pads a single-digit month and day', () => {
    expect(localDateIn('UTC', '2026-01-05T12:00:00Z')).toBe('2026-01-05');
  });

  it('falls back rather than throwing on an unrecognised timezone', () => {
    expect(localDateIn('Not/AZone', '2026-08-23T12:00:00Z')).toMatch(
      /^\d{4}-\d{2}-\d{2}$/
    );
  });

  /**
   * Only a malformed listing produces this, and the fallback zone cannot save
   * it — the instant itself is the problem. An empty string is never greater
   * than a real date, so such a journal is left out of the offer rather than
   * shown under a date nobody can trust.
   */
  it('answers an empty date for an unparseable instant rather than throwing', () => {
    expect(localDateIn('UTC', 'not-a-date')).toBe('');
  });

  it('leaves a journal with an unparseable date out of the offer', () => {
    const options = futureJournalOptions(
      [
        journal('broken', 'not-a-date'),
        journal('fine', '2026-08-24T12:00:00Z'),
      ],
      { timezone: 'UTC', today: '2026-08-23' }
    );

    expect(options.map(option => option.id)).toEqual(['fine']);
  });
});

describe('todayIn', () => {
  it('answers the local date of the supplied instant', () => {
    expect(todayIn(SYDNEY, new Date('2026-08-23T14:00:00Z'))).toBe(
      '2026-08-24'
    );
  });

  it('reads the clock when no instant is supplied', () => {
    expect(todayIn('UTC')).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe('addDaysToIsoDate', () => {
  it('moves a date forward by whole days', () => {
    expect(addDaysToIsoDate('2026-08-23', 90)).toBe('2026-11-21');
  });

  it('crosses a month and a year boundary', () => {
    expect(addDaysToIsoDate('2026-12-30', 3)).toBe('2027-01-02');
  });
});

describe('futureJournalOptions', () => {
  const today = '2026-08-23';
  const context = { timezone: 'UTC', today };

  it('returns nothing for an empty listing', () => {
    expect(futureJournalOptions([], context)).toEqual([]);
  });

  /**
   * The invariant the picker exists to respect: "at the moment a due journal
   * is set, that journal's date must be in the future". Today is not the
   * future — the backend's `is_future_dated` is strictly-after — so a journal
   * dated today is refused and must not be offered.
   */
  it('drops a journal dated today and one dated yesterday, keeping tomorrow', () => {
    const options = futureJournalOptions(
      [
        journal('1', '2026-08-22T12:00:00Z'),
        journal('2', '2026-08-23T12:00:00Z'),
        journal('3', '2026-08-24T12:00:00Z'),
      ],
      context
    );

    expect(options.map(option => option.id)).toEqual(['3']);
  });

  /**
   * The listing arrives newest-first because that is the only order the
   * endpoint has. The fixture is deliberately in that order, so dropping the
   * sort fails this test rather than passing by accident.
   */
  it('returns the nearest future journal first, from a newest-first listing', () => {
    const options = futureJournalOptions(
      [
        journal('far', '2026-10-01T12:00:00Z'),
        journal('mid', '2026-09-01T12:00:00Z'),
        journal('near', '2026-08-24T12:00:00Z'),
      ],
      context
    );

    expect(options.map(option => option.id)).toEqual(['near', 'mid', 'far']);
  });

  it('orders two journals on the same day by the moment each starts', () => {
    const options = futureJournalOptions(
      [
        journal('afternoon', '2026-08-24T15:00:00Z'),
        journal('morning', '2026-08-24T09:00:00Z'),
      ],
      context
    );

    expect(options.map(option => option.id)).toEqual(['morning', 'afternoon']);
  });

  it('carries the journal id, title and resolved date', () => {
    const [option] = futureJournalOptions(
      [journal('7', '2026-08-24T12:00:00Z', { title: 'Kanangra planning' })],
      context
    );

    expect(option).toMatchObject({
      id: '7',
      title: 'Kanangra planning',
      date: '2026-08-24',
      cancelled: false,
    });
  });

  /**
   * The whole reason the timezone is a parameter: judged in UTC this journal
   * is dated today and would be dropped; in Sydney it is tomorrow. The rule
   * the server applies is the user's configured zone, so this must follow it.
   */
  it('resolves dates in the supplied timezone, not the browser default', () => {
    const listing = [journal('1', '2026-08-23T14:00:00Z')];

    expect(futureJournalOptions(listing, { timezone: 'UTC', today })).toEqual(
      []
    );
    expect(
      futureJournalOptions(listing, { timezone: SYDNEY, today }).map(
        option => option.date
      )
    ).toEqual(['2026-08-24']);
  });

  it('marks a cancelled event journal', () => {
    const [option] = futureJournalOptions(
      [cancelledEvent('9', '2026-08-24T12:00:00Z')],
      context
    );

    expect(option.cancelled).toBe(true);
  });

  it('still offers a cancelled journal rather than hiding it', () => {
    const options = futureJournalOptions(
      [cancelledEvent('9', '2026-08-24T12:00:00Z')],
      context
    );

    expect(options).toHaveLength(1);
  });

  it('does not mark a journal that carries no event type data', () => {
    const [option] = futureJournalOptions(
      [journal('1', '2026-08-24T12:00:00Z')],
      context
    );

    expect(option.cancelled).toBe(false);
  });

  /**
   * `invited` and `tentative` are not cancellations — the same reading the
   * backend's `find_cancelled_journal_ids` takes.
   */
  it.each([EventState.CONFIRMED, EventState.TENTATIVE, EventState.INVITED])(
    'does not mark an event in the %s state',
    state => {
      const listing = [
        journal('1', '2026-08-24T12:00:00Z', {
          types: [JournalType.EVENT],
          type_data: {
            [JournalType.EVENT]: {
              calendar_id: 'cal-1',
              is_all_day: true,
              sync_invitees: false,
              private_description: false,
              event_state: state,
            },
          },
        }),
      ];

      expect(futureJournalOptions(listing, context)[0].cancelled).toBe(false);
    }
  );
});

describe('formatFutureJournalDate', () => {
  /**
   * The formatter itself is `date-utils`' and is tested there. What this pins
   * is that the picker's name for it is that same function, so the two cannot
   * drift into two format strings.
   */
  it('is date-utils’ ISO-date formatter under the name the picker uses', () => {
    expect(formatFutureJournalDate).toBe(formatIsoDate);
  });
});
