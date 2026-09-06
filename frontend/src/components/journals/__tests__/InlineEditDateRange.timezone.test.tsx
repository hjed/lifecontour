/**
 * Timezone contract for the instants InlineEditDateRange writes.
 *
 * @jest-environment <rootDir>/jest.timezone-environment.cjs
 * @jest-environment-options {"timezone": "America/New_York"}
 *
 * A journal's `event_date_range` bounds are the UTC instant of *local*
 * midnight — what `JournalCreateForm` sends, what the Google sync stores since
 * #1385, and what the backend re-reads through the event's zone. This editor
 * used to zero the **UTC** clock instead, so an edited journal ended up at a
 * different instant from a created one: harmless anywhere ahead of UTC, and a
 * day early anywhere behind it (issue #1384).
 *
 * These cases therefore only mean anything with a **negative** offset pinned,
 * which is why they live apart from `InlineEditDateRange.test.tsx` — that
 * file's display assertions read in the ambient zone and must keep doing so.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InlineEditDateRange } from '@/components/journals/InlineEditDateRange';
import { useJournalTimezone } from '@/lib/api/settings';
import type { EventDateRange } from '@/types/journals';

// The configured zone is the pinned one, so these cases isolate the
// convention itself; `InlineEditDateRange.cross-timezone.test.tsx` is where
// the two zones are made to disagree.
jest.mock('@/lib/api/settings', () => ({
  useJournalTimezone: jest.fn(),
}));

// 15 and 16 January 2025 as the app stores them for a New York user: local
// midnight, which is 05:00Z because January is outside daylight saving.
const LOCAL_MIDNIGHT_15TH = '2025-01-15T05:00:00.000Z';
const LOCAL_MIDNIGHT_16TH = '2025-01-16T05:00:00.000Z';

async function saveWithoutChangingTheRange(
  value: EventDateRange
): Promise<EventDateRange> {
  const onSave = jest.fn().mockResolvedValue(undefined);
  const user = userEvent.setup();
  render(<InlineEditDateRange value={value} onSave={onSave} />);

  await user.click(screen.getByRole('button'));
  await user.click(await screen.findByLabelText('Save date range'));

  await waitFor(() => expect(onSave).toHaveBeenCalled());
  return onSave.mock.calls[0][0] as EventDateRange;
}

describe('InlineEditDateRange in a zone behind UTC', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useJournalTimezone as jest.Mock).mockReturnValue({
      timezone: 'America/New_York',
      userTimezone: 'America/New_York',
    });
  });

  it('sanity check: the pinned zone is in effect', () => {
    expect(new Date(2025, 0, 15).toISOString()).toBe(LOCAL_MIDNIGHT_15TH);
  });

  it('sends a correctly stored range back unchanged', async () => {
    const saved = await saveWithoutChangingTheRange({
      start: LOCAL_MIDNIGHT_15TH,
      end: LOCAL_MIDNIGHT_16TH,
    });

    expect(saved).toEqual({
      start: LOCAL_MIDNIGHT_15TH,
      end: LOCAL_MIDNIGHT_16TH,
    });
  });

  it('writes the end bound at local midnight, not the end of the day', async () => {
    const saved = await saveWithoutChangingTheRange({
      start: LOCAL_MIDNIGHT_15TH,
      end: LOCAL_MIDNIGHT_15TH,
    });

    // The inclusive last day at midnight is what the create form writes, so a
    // single-day range has start === end. 23:59:59.999 was a second convention.
    expect(saved.end).toBe(LOCAL_MIDNIGHT_15TH);
    expect(saved.start).toBe(saved.end);
  });

  it('normalises a legacy UTC-midnight range onto the day it displays', async () => {
    // What the pre-#1385 Google sync left behind. A New York reader sees this
    // as 14 January (19:00 the evening before), and the picker opens on that
    // day — so saving has to write that day's local midnight, not re-emit an
    // instant the editor never showed.
    const saved = await saveWithoutChangingTheRange({
      start: '2025-01-15T00:00:00.000Z',
      end: '2025-01-15T00:00:00.000Z',
    });

    expect(saved).toEqual({
      start: '2025-01-14T05:00:00.000Z',
      end: '2025-01-14T05:00:00.000Z',
    });
  });
});
