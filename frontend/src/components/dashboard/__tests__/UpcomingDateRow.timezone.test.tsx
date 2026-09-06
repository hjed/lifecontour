/**
 * @jest-environment <rootDir>/jest.timezone-environment.cjs
 * @jest-environment-options {"timezone": "America/New_York"}
 *
 * The upcoming-date row **near midnight, in a zone that is not the server's**.
 *
 * Two of the row's values were resolved by the server against the user's
 * configured timezone: `occurs_on` is a calendar day in that zone, and
 * `days_away` counts from the window's first day in it. A row that worked
 * either out from the browser's clock would be right most of the time and
 * wrong in the hours that matter, so this pins both against a browser whose
 * own answer would differ.
 *
 * The setup is chosen so a browser-derived answer is *visibly* wrong rather
 * than merely unproven: it is 23:30 on 30 July in New York, the occurrence is
 * 31 July, and the server — which windowed in Sydney, already a day ahead —
 * says the date is two days off. Browser arithmetic would say "Today"; parsing
 * `occurs_on` as an instant would label it Thursday 30 July. Both are asserted
 * against.
 */

import { render, screen } from '@testing-library/react';
import { UpcomingDateRow } from '../UpcomingDateRow';
import type { HomeDashboardUpcomingDate } from '@/lib/api/home-dashboard';
import { ImportantDateTypeEnum } from '@/types/contacts';

/** 23:30 on 30 July in New York — half an hour before the local day turns. */
const NEW_YORK_NEAR_MIDNIGHT = new Date('2026-07-31T03:30:00Z');

/** As the server resolved it in Sydney, where it is already 31 July. */
const SYDNEY_RESOLVED: HomeDashboardUpcomingDate = {
  contact_id: 7,
  contact_name: 'Ada Lovelace',
  photo_url: null,
  date_type: ImportantDateTypeEnum.BIRTHDAY,
  custom_date_type_name: null,
  occurs_on: '2026-07-31',
  days_away: 2,
  years: 35,
  observed_for_leap_day: false,
};

describe('UpcomingDateRow near midnight in a non-UTC zone', () => {
  beforeEach(() => {
    jest.useFakeTimers({ now: NEW_YORK_NEAR_MIDNIGHT });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('confirms the browser really is on the previous local day', () => {
    // Not a test of the row — a test of the fixture. Without this the two
    // assertions below could pass in a zone where nothing was ever at risk.
    expect(new Date().getDate()).toBe(30);
  });

  it('reads the gap from the payload, not from the browser clock', () => {
    render(<UpcomingDateRow date={SYDNEY_RESOLVED} />);

    expect(screen.getByTestId('upcoming-date-chip')).toHaveTextContent(
      'in 2 days'
    );
    expect(screen.getByTestId('upcoming-date-chip')).not.toHaveTextContent(
      'Today'
    );
  });

  it('labels the occurrence with its own calendar day, not an instant', () => {
    render(<UpcomingDateRow date={SYDNEY_RESOLVED} />);

    expect(screen.getByTestId('upcoming-date-when')).toHaveTextContent(
      'Friday, 31 July'
    );
  });
});
