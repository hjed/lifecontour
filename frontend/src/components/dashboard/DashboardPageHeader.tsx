/**
 * DashboardPageHeader — the dashboard's page header (**W2**).
 *
 * "Today" over the full localised date and a line saying what the page is for.
 *
 * The date is the **server's** anchor — today in the user's configured
 * timezone, carried in the payload's `meta.anchor` — not the browser's. The two
 * can differ, and every window on the page is drawn against the server's day,
 * so labelling the page with the browser's would put a date on evidence that
 * was gathered for a different one. Until the anchor arrives the header shows
 * no date at all rather than guessing one: a wrong date is worse than none.
 */

import { formatIsoDateLong } from '@/lib/date-utils';

interface DashboardPageHeaderProps {
  /** Today in the user's configured zone (`YYYY-MM-DD`), from `meta.anchor`. */
  readonly anchorDate: string | undefined;
}

const FRAMING_LINE =
  'your day, what is coming up, and what you said you would do.';

export function DashboardPageHeader({ anchorDate }: DashboardPageHeaderProps) {
  return (
    <header className='space-y-1'>
      <h1 className='text-2xl font-bold tracking-tight'>Today</h1>
      <p className='text-muted-foreground'>
        {anchorDate && (
          <>
            <span data-testid='dashboard-anchor-date'>
              {formatIsoDateLong(anchorDate)}
            </span>
            {' — '}
          </>
        )}
        {FRAMING_LINE}
      </p>
    </header>
  );
}
