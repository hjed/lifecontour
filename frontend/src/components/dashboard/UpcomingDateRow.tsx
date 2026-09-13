/**
 * UpcomingDateRow — one important contact date as the dashboard draws it
 * (**W31**).
 *
 * A bordered rounded row with a hover shadow, holding a ringed avatar, the
 * contact's name as a link to them, a colour-coded outline badge naming the
 * kind of date and the count it makes, the occurrence written out in full, and
 * a right-aligned bordered chip in tabular figures saying how far off it is.
 *
 * A pure function of the payload row, with no query and **no clock**. That is
 * the load-bearing part rather than a convenience: `occurs_on` is a calendar
 * day the server resolved in the user's configured zone and `days_away` counts
 * from the window's first day in it, so both are rendered as given. Working
 * either out here would consult the *browser's* zone, which near midnight can
 * answer a day out — pinned in `UpcomingDateRow.timezone.test.tsx`.
 *
 * **The 29 February substitution is shown, not swallowed.** A leap-day date
 * observed on the 28th would otherwise read as a quietly wrong day; the
 * payload flags it precisely so a row can account for itself.
 *
 * **The wording lives in `upcoming-dates-display`**, not here — a custom
 * date's own name, the `turns 35` / `34 years` suffix and the badge colour are
 * product rules that a test should be able to assert without a DOM.
 */

import Link from 'next/link';
import type { Route } from 'next';
import { CalendarClock } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import type { HomeDashboardUpcomingDate } from '@/lib/api/home-dashboard';
import { nameParts } from '@/lib/contact-names';
import { formatIsoWeekdayDate } from '@/lib/date-utils';
import {
  dateBadgeLabel,
  dateTypeBadgeClassName,
  daysAwayLabel,
} from '@/lib/upcoming-dates-display';
import { cn } from '@/lib/utils';

interface UpcomingDateRowProps {
  readonly date: HomeDashboardUpcomingDate;
}

export function UpcomingDateRow({ date }: UpcomingDateRowProps) {
  const { first, last } = nameParts(date.contact_name);

  return (
    <li
      data-testid='upcoming-date'
      className='border-border rounded-lg border p-3 transition-shadow hover:shadow-sm'
    >
      <div className='flex min-w-0 items-center gap-3'>
        <ContactAvatar
          firstName={first}
          lastName={last}
          size='md'
          className='ring-background shrink-0 ring-2'
          {...(date.photo_url ? { imageUrl: date.photo_url } : {})}
        />

        {/* `min-w-0` so a long name or a long custom date type wraps inside
            the row rather than pushing the chip out of the column (W3). */}
        <div className='min-w-0 flex-1'>
          <Link
            href={`/contacts/${date.contact_id}` as Route}
            className='min-w-0 font-medium break-words underline-offset-4 hover:underline'
          >
            {date.contact_name}
          </Link>

          <div className='mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1'>
            <Badge
              variant='outline'
              data-testid='upcoming-date-badge'
              // A custom date type is free text and can be one unbroken token.
              className={cn(
                'break-words',
                dateTypeBadgeClassName(date.date_type)
              )}
            >
              {dateBadgeLabel(date)}
            </Badge>
            <span
              data-testid='upcoming-date-when'
              className='text-muted-foreground min-w-0 text-sm'
            >
              {formatIsoWeekdayDate(date.occurs_on)}
            </span>
            {date.observed_for_leap_day && (
              <span
                data-testid='upcoming-date-observed'
                className='text-muted-foreground text-xs'
              >
                (observed — no 29 February this year)
              </span>
            )}
          </div>
        </div>

        <span
          data-testid='upcoming-date-chip'
          className={cn(
            'border-border text-muted-foreground flex shrink-0 items-center gap-1',
            'rounded-md border px-2 py-0.5 text-xs tabular-nums'
          )}
        >
          <CalendarClock className='h-3 w-3' aria-hidden='true' />
          {daysAwayLabel(date.days_away)}
        </span>
      </div>
    </li>
  );
}
