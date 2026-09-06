/**
 * @jest-environment jsdom
 *
 * One upcoming contact date as the dashboard draws it (**W31**).
 *
 * A pure function of a payload row — no query, no clock — so these render it
 * directly. What is asserted is the row's *content*: whose date it is, where
 * the name goes, what the badge says at each precision, and that the two
 * values the server resolved (`occurs_on`, `days_away`) are the ones drawn.
 *
 * The near-midnight non-UTC case the phase asks for lives in
 * `UpcomingDateRow.timezone.test.tsx`, which needs a pinned process zone.
 */

import { render, screen } from '@testing-library/react';
import { UpcomingDateRow } from '../UpcomingDateRow';
import type { HomeDashboardUpcomingDate } from '@/lib/api/home-dashboard';
import { ImportantDateTypeEnum } from '@/types/contacts';

function upcomingDate(
  overrides: Partial<HomeDashboardUpcomingDate> = {}
): HomeDashboardUpcomingDate {
  return {
    contact_id: 7,
    contact_name: 'Ada Lovelace',
    photo_url: null,
    date_type: ImportantDateTypeEnum.BIRTHDAY,
    custom_date_type_name: null,
    occurs_on: '2026-07-31',
    days_away: 2,
    years: 35,
    observed_for_leap_day: false,
    ...overrides,
  };
}

/**
 * Make jsdom report images as loaded.
 *
 * Radix withholds the `<img>` until the browser reports a successful load, and
 * jsdom never fetches anything — so without this the photo branch renders
 * nothing at all and a row that dropped `photo_url` on the floor would pass.
 * Restored afterwards so nothing else in the worker inherits it.
 */
const IMAGE_PROTOTYPE = window.HTMLImageElement.prototype;
const REAL_COMPLETE = Object.getOwnPropertyDescriptor(
  IMAGE_PROTOTYPE,
  'complete'
);
const REAL_NATURAL_WIDTH = Object.getOwnPropertyDescriptor(
  IMAGE_PROTOTYPE,
  'naturalWidth'
);

function withLoadedImages(): void {
  Object.defineProperty(IMAGE_PROTOTYPE, 'complete', {
    configurable: true,
    get: () => true,
  });
  Object.defineProperty(IMAGE_PROTOTYPE, 'naturalWidth', {
    configurable: true,
    get: () => 1,
  });
}

function restoreImages(): void {
  if (REAL_COMPLETE) {
    Object.defineProperty(IMAGE_PROTOTYPE, 'complete', REAL_COMPLETE);
  }
  if (REAL_NATURAL_WIDTH) {
    Object.defineProperty(IMAGE_PROTOTYPE, 'naturalWidth', REAL_NATURAL_WIDTH);
  }
}

describe('UpcomingDateRow', () => {
  it('links the contact by name to their page', () => {
    render(<UpcomingDateRow date={upcomingDate()} />);

    const link = screen.getByRole('link', { name: 'Ada Lovelace' });
    expect(link).toHaveAttribute('href', '/contacts/7');
  });

  it('names the contact on their avatar', () => {
    render(<UpcomingDateRow date={upcomingDate()} />);

    expect(
      screen.getByRole('img', { name: /ada lovelace/i })
    ).toBeInTheDocument();
  });

  it('shows the photo the payload carries', async () => {
    withLoadedImages();
    try {
      render(
        <UpcomingDateRow
          date={upcomingDate({ photo_url: 'https://example.test/ada.jpg' })}
        />
      );

      expect(await screen.findByTestId('avatar-contact-image')).toHaveAttribute(
        'src',
        'https://example.test/ada.jpg'
      );
    } finally {
      restoreImages();
    }
  });

  it('falls back to initials when there is no photo', () => {
    render(<UpcomingDateRow date={upcomingDate({ photo_url: null })} />);

    expect(
      screen.queryByTestId('avatar-contact-image')
    ).not.toBeInTheDocument();
    expect(screen.getByTestId('avatar-contact-fallback')).toHaveTextContent(
      'AL'
    );
  });

  // The two precisions the section can produce, which is what decides whether
  // the badge carries a derived count at all.
  it('carries the derived age where the stored precision allows one', () => {
    render(<UpcomingDateRow date={upcomingDate({ years: 35 })} />);

    expect(screen.getByTestId('upcoming-date-badge')).toHaveTextContent(
      'Birthday · turns 35'
    );
  });

  it('degrades to the bare type where it does not', () => {
    render(<UpcomingDateRow date={upcomingDate({ years: null })} />);

    expect(screen.getByTestId('upcoming-date-badge')).toHaveTextContent(
      'Birthday'
    );
    expect(screen.getByTestId('upcoming-date-badge')).not.toHaveTextContent(
      'turns'
    );
  });

  it('shows a custom date under its own name', () => {
    render(
      <UpcomingDateRow
        date={upcomingDate({
          date_type: ImportantDateTypeEnum.CUSTOM,
          custom_date_type_name: 'Sobriety',
          years: 3,
        })}
      />
    );

    expect(screen.getByTestId('upcoming-date-badge')).toHaveTextContent(
      'Sobriety · 3 years'
    );
    expect(screen.queryByText(/custom/i)).not.toBeInTheDocument();
  });

  it('writes the occurrence date out in full', () => {
    render(
      <UpcomingDateRow date={upcomingDate({ occurs_on: '2026-07-31' })} />
    );

    expect(screen.getByTestId('upcoming-date-when')).toHaveTextContent(
      'Friday, 31 July'
    );
  });

  it.each([
    [0, 'Today'],
    [1, 'Tomorrow'],
    [3, 'in 3 days'],
  ])('reads a %i-day gap as "%s"', (daysAway, expected) => {
    render(<UpcomingDateRow date={upcomingDate({ days_away: daysAway })} />);

    expect(screen.getByTestId('upcoming-date-chip')).toHaveTextContent(
      expected
    );
  });

  // W31 asks for tabular figures so the chips line up down the column rather
  // than jittering as the digit widths change.
  it('draws the gap in tabular figures', () => {
    render(<UpcomingDateRow date={upcomingDate()} />);

    expect(screen.getByTestId('upcoming-date-chip')).toHaveClass(
      'tabular-nums'
    );
  });

  // A 29 February date shown on the 28th would otherwise look like a wrong
  // date. The payload flags the substitution precisely so a row can say so.
  it('says when the day stands in for a 29 February', () => {
    render(
      <UpcomingDateRow
        date={upcomingDate({
          occurs_on: '2027-02-28',
          observed_for_leap_day: true,
        })}
      />
    );

    expect(screen.getByTestId('upcoming-date-observed')).toBeInTheDocument();
  });

  it('says nothing about leap days on an ordinary date', () => {
    render(<UpcomingDateRow date={upcomingDate()} />);

    expect(
      screen.queryByTestId('upcoming-date-observed')
    ).not.toBeInTheDocument();
  });

  it('marks its decorative icons as hidden from assistive tech', () => {
    const { container } = render(<UpcomingDateRow date={upcomingDate()} />);

    container.querySelectorAll('svg').forEach(icon => {
      expect(icon).toHaveAttribute('aria-hidden', 'true');
    });
  });
});
