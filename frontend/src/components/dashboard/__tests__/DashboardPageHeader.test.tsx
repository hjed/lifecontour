/**
 * @jest-environment jsdom
 *
 * The dashboard's page header (**W2**): "Today", the full localised date, and
 * the line that says what the page is for.
 *
 * The date is the *server's* anchor, so these tests render the header against
 * an explicit anchor rather than the clock, and one of them pins the case a
 * browser-derived date would get wrong.
 */

import { render, screen } from '@testing-library/react';
import { DashboardPageHeader } from '../DashboardPageHeader';

describe('DashboardPageHeader', () => {
  it('is headed "Today"', () => {
    render(<DashboardPageHeader anchorDate='2026-07-29' />);

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Today'
    );
  });

  it('writes the anchor day in full', () => {
    render(<DashboardPageHeader anchorDate='2026-07-29' />);

    expect(screen.getByText(/Wednesday, 29 July 2026/)).toBeInTheDocument();
  });

  it('carries the framing line', () => {
    render(<DashboardPageHeader anchorDate='2026-07-29' />);

    expect(
      screen.getByText(
        /your day, what is coming up, and what you said you would do/i
      )
    ).toBeInTheDocument();
  });

  /**
   * The anchor is a calendar date already resolved in the user's configured
   * zone. Parsing it as an instant would shift it a day in any zone behind
   * UTC, so a 1 January anchor is the case that catches it.
   */
  it('does not shift the anchor day', () => {
    render(<DashboardPageHeader anchorDate='2026-01-01' />);

    expect(screen.getByText(/Thursday, 1 January 2026/)).toBeInTheDocument();
  });

  it('still shows the heading before the anchor has arrived, without guessing a date', () => {
    render(<DashboardPageHeader anchorDate={undefined} />);

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Today'
    );
    // No date at all is right while the server's day is unknown: the browser's
    // today can differ from it, and a wrong date is worse than none.
    expect(screen.queryByText(/\d{4}/)).not.toBeInTheDocument();
    expect(
      screen.getByText(
        /your day, what is coming up, and what you said you would do/i
      )
    ).toBeInTheDocument();
  });
});
