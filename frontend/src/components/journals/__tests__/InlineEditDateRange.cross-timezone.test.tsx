/**
 * The editor when the browser is somewhere the user is not.
 *
 * @jest-environment <rootDir>/jest.timezone-environment.cjs
 * @jest-environment-options {"timezone": "Australia/Sydney"}
 *
 * A journal's `event_date_range` bounds are the UTC instant of midnight on a
 * calendar day *in a zone*, and the editor used to pick that zone from the
 * browser. For a user travelling, or an event imported from a foreign-zone
 * calendar, that is not the user's zone: a New York 15 January event stored as
 * `2025-01-15T05:00Z` opened in a Sydney browser was written back as
 * `2025-01-14T13:00Z` — 14 January, read in New York (issue #1401).
 *
 * These cases therefore pin a browser zone that **disagrees** with the
 * configured one, which is the only arrangement in which the bug is visible;
 * `InlineEditDateRange.timezone.test.tsx` covers the same-zone contract.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InlineEditDateRange } from '@/components/journals/InlineEditDateRange';
import { journalTimezone, useJournalTimezone } from '@/lib/api/settings';
import type { EventDateRange } from '@/types/journals';

// `journalTimezone` is kept real — the precedence it encodes is the thing
// under test here as much as the component is, and reimplementing it in a
// double would let the two drift apart, which is the very defect this file
// exists to pin down.
jest.mock('@/lib/api/settings', () => ({
  ...jest.requireActual('@/lib/api/settings'),
  useJournalTimezone: jest.fn(),
}));

/** The user's own configured zone, as the settings read has resolved it. */
let configuredZone = 'America/New_York';

function useResolvedZones(eventTimezone?: string | null) {
  return {
    timezone: journalTimezone(eventTimezone, configuredZone),
    userTimezone: configuredZone,
  };
}

// 15 January 2025 as the app stores it for a New York user: local midnight,
// which is 05:00Z because January is outside daylight saving. Sixteen hours
// later in Sydney, so a browser-anchored editor reads it as the afternoon of
// the 15th and writes back the *Sydney* 15th — a different instant.
const NEW_YORK_15TH = '2025-01-15T05:00:00.000Z';
const NEW_YORK_16TH = '2025-01-16T05:00:00.000Z';

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

describe('InlineEditDateRange with a configured zone the browser does not share', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    configuredZone = 'America/New_York';
    (useJournalTimezone as jest.Mock).mockImplementation(useResolvedZones);
  });

  it('sanity check: the browser zone and the configured zone differ', () => {
    expect(new Date(2025, 0, 15).toISOString()).toBe(
      '2025-01-14T13:00:00.000Z'
    );
    expect(configuredZone).toBe('America/New_York');
  });

  it('shows the day the event falls on in the configured zone', () => {
    render(
      <InlineEditDateRange
        value={{ start: NEW_YORK_15TH, end: NEW_YORK_16TH }}
        onSave={jest.fn()}
      />
    );

    expect(screen.getByRole('button')).toHaveTextContent(/15.*16 Jan 2025/);
  });

  it('sends a correctly stored range back unchanged', async () => {
    const saved = await saveWithoutChangingTheRange({
      start: NEW_YORK_15TH,
      end: NEW_YORK_16TH,
    });

    // The whole of the issue in one assertion: opening and saving an event
    // from a browser in another zone must be a no-op, not a day's drift.
    expect(saved).toEqual({ start: NEW_YORK_15TH, end: NEW_YORK_16TH });
  });

  it('does not push a year-end event into the next year', async () => {
    // 31 December in New York is 1 January in Sydney. A browser-anchored write
    // moved this event forward a day — and across a year boundary, where the
    // day being wrong is at its most visible.
    const newYearsEve = '2026-01-01T05:00:00.000Z';

    const saved = await saveWithoutChangingTheRange({
      start: newYearsEve,
      end: newYearsEve,
    });

    expect(saved).toEqual({ start: newYearsEve, end: newYearsEve });
  });

  /**
   * The configured zone is not known on the first render — the settings read
   * has not landed — so the editor starts on the browser's zone and switches
   * when it does. Anything the picker resolved under the old zone has to
   * follow, or a save combines days resolved in one zone with an anchor in
   * another: the very mismatch this component was changed to remove.
   */
  it('follows the configured zone when it resolves after the editor opened', async () => {
    // Read in Sydney this is the 15th (11:00); in New York it is still the
    // evening of the 14th. So the two zones disagree about which day the
    // picker should be sitting on.
    const legacyUtcMidnight = '2025-01-15T00:00:00.000Z';
    const onSave = jest.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();

    // The settings read has not landed yet: the browser's zone stands in.
    configuredZone = 'Australia/Sydney';
    const { rerender } = render(
      <InlineEditDateRange
        value={{ start: legacyUtcMidnight, end: legacyUtcMidnight }}
        onSave={onSave}
      />
    );

    await user.click(screen.getByRole('button'));
    expect(await screen.findByLabelText('Save date range')).toBeVisible();

    // ...and now it lands, with a zone the browser does not share.
    configuredZone = 'America/New_York';
    rerender(
      <InlineEditDateRange
        value={{ start: legacyUtcMidnight, end: legacyUtcMidnight }}
        onSave={onSave}
      />
    );

    await user.click(screen.getByLabelText('Save date range'));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    // The New York day, not the Sydney day written with a New York anchor.
    expect(onSave.mock.calls[0][0]).toEqual({
      start: '2025-01-14T05:00:00.000Z',
      end: '2025-01-14T05:00:00.000Z',
    });
  });

  /**
   * An event imported from a foreign-zone calendar records its own zone, and
   * that zone is what the backend and the Google worker read its bounds
   * through. Anchoring a save anywhere else — the user's configured zone
   * included — moves the event a calendar day for every one of those readers.
   */
  describe('for a journal that records its own zone', () => {
    // A Los Angeles event: 20 March at LA midnight, which is 07:00Z because
    // March is inside daylight saving there. Neither Sydney (the browser) nor
    // New York (the user) agrees with it.
    const LOS_ANGELES_20TH = '2025-03-20T07:00:00.000Z';

    function renderWithEventZone(onSave = jest.fn()) {
      return render(
        <InlineEditDateRange
          value={{ start: LOS_ANGELES_20TH, end: LOS_ANGELES_20TH }}
          eventTimezone='America/Los_Angeles'
          onSave={onSave}
        />
      );
    }

    it('shows the day the event falls on in its own zone', () => {
      renderWithEventZone();

      expect(screen.getByRole('button')).toHaveTextContent('20 Mar 2025');
    });

    it('sends the range back unchanged rather than re-anchoring it', async () => {
      const onSave = jest.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      renderWithEventZone(onSave);

      await user.click(screen.getByRole('button'));
      await user.click(await screen.findByLabelText('Save date range'));

      await waitFor(() => expect(onSave).toHaveBeenCalled());
      expect(onSave.mock.calls[0][0]).toEqual({
        start: LOS_ANGELES_20TH,
        end: LOS_ANGELES_20TH,
      });
    });

    it('names the zone, because it is not the one the user reads dates in', () => {
      renderWithEventZone();

      expect(screen.getByRole('button')).toHaveTextContent(
        'America/Los_Angeles'
      );
    });

    it('says so in the accessible name too', () => {
      renderWithEventZone();

      expect(screen.getByRole('button')).toHaveAccessibleName(
        expect.stringContaining('America/Los_Angeles') as unknown as string
      );
    });

    it('keeps naming the zone while the picker is open', async () => {
      const user = userEvent.setup();
      renderWithEventZone();

      await user.click(screen.getByRole('button'));

      expect(await screen.findByLabelText('Save date range')).toBeVisible();
      expect(screen.getByTestId('date-range-timezone')).toHaveTextContent(
        'America/Los_Angeles'
      );
    });

    it('says nothing when the event is in the zone the user already reads in', () => {
      render(
        <InlineEditDateRange
          value={{ start: NEW_YORK_15TH, end: NEW_YORK_15TH }}
          eventTimezone='America/New_York'
          onSave={jest.fn()}
        />
      );

      expect(
        screen.queryByTestId('date-range-timezone')
      ).not.toBeInTheDocument();
    });
  });

  it('normalises a legacy UTC-midnight range onto the day it displays', async () => {
    // What the pre-#1385 Google sync left behind, read by a New York user: the
    // evening of the 14th, so the picker opens on the 14th and saving has to
    // write that day's New York midnight — not the Sydney day the browser
    // would have reported, and not an instant the editor never showed.
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
