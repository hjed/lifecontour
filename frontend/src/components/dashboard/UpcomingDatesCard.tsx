/**
 * UpcomingDatesCard — important contact dates in the coming week (**W30**–
 * **W32**).
 *
 * Read from the dashboard payload the page already fetched: the card calls
 * `useHomeDashboard()` itself, the arrangement the summary and agenda cards
 * established, so it owns its own loading and unavailable renderings and still
 * costs the page nothing — every caller shares one query key and dedupes into
 * a single request.
 *
 * **The card draws the list it is given and does not re-sort it.** Date
 * ascending, then contact importance descending, is the server's rule (Phase
 * 11); the payload deliberately publishes none of the importance signals it
 * ranked by, so the card could not reproduce that order even if it tried.
 *
 * **The cap lives here, and only here** (**W32**, wireframe gap 3, settled in
 * Phase 11): the server sends the *whole* window with its `total`, three rows
 * are drawn, and the show-more reveals the remainder **in place** from data
 * already held. That is what makes the show-more free — asserted against the
 * request count, not just the DOM — and it is why the button names `total`
 * rather than the number hidden behind the cap.
 *
 * Three things the list can hold nothing for, kept apart on purpose: **nothing
 * coming up** is a real answer and gets the single **W29**-idiom line the
 * wireframe does not draw (gap 2); the query still being **in flight** gets the
 * pulsing row skeleton and the section coming back **unavailable** its own
 * centred line, because "no important dates" would be a false claim about
 * either. Both are `DashboardSectionPlaceholder`'s; this card supplies only
 * their wording.
 */

'use client';

import { useState } from 'react';
import { CalendarOff, Star } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DashboardSectionCard } from './DashboardSectionCard';
import { DashboardSectionPlaceholder } from './DashboardSectionPlaceholder';
import { UpcomingDateRow } from './UpcomingDateRow';
import {
  DashboardSectionStatus,
  useHomeDashboard,
} from '@/lib/api/home-dashboard';
import type { HomeDashboardUpcomingDate } from '@/lib/api/home-dashboard';
import { showAllLabel } from '@/lib/upcoming-dates-display';

/** The section's wireframe copy, in one place so the page and its tests agree. */
export const UPCOMING_DATES_SECTION = {
  icon: Star,
  iconChipClassName: 'bg-chart-1 text-white',
  title: 'Upcoming dates',
  description: 'Important dates for your contacts over the next seven days.',
  listLabel: 'Upcoming contact dates',
  emptyIcon: CalendarOff,
  emptyMessage: 'No important dates in the next seven days.',
} as const;

/** What the card says while it has no list to draw. Not shell props. */
const UPCOMING_DATES_PLACEHOLDER_COPY = {
  loading: 'Loading upcoming dates...',
  unavailable: 'Upcoming dates are unavailable.',
} as const;

/**
 * How many occurrences are drawn before the show-more (**W32**).
 *
 * Three, as the wireframe draws it. Symmetry with the tasks section's five was
 * the alternative and was declined in Phase 11: **W3** already grants the three
 * columns independent heights, so it buys nothing the wireframe did not draw.
 */
export const VISIBLE_UPCOMING_DATES = 3;

export function UpcomingDatesCard() {
  const { data, isPending } = useHomeDashboard();
  const [expanded, setExpanded] = useState(false);

  const section = data?.data.attributes.upcoming_dates;
  const upcoming =
    section?.status === DashboardSectionStatus.READY ? section.data : null;

  // Guarded rather than trusted, for the reason the agenda card guards its
  // tomorrow: the type promises an array on every ready section, but a payload
  // that broke that used to throw out of render and take the *whole page* with
  // it. "Sections render independently" has to survive a section that breaks
  // its contract, not only one that reports itself unavailable.
  const dates: HomeDashboardUpcomingDate[] | null = Array.isArray(
    upcoming?.dates
  )
    ? upcoming.dates
    : null;

  // `total` is the window's own count and is what the show-more names. It can
  // exceed what is drawn but never what was sent, so the button is offered
  // against the list's own length — a `total` that disagreed with the payload
  // would otherwise offer to reveal rows that are not there.
  const total = dates?.length ?? 0;
  const shown =
    expanded || dates === null ? dates : dates.slice(0, VISIBLE_UPCOMING_DATES);
  const hasMore = !expanded && total > VISIBLE_UPCOMING_DATES;

  return (
    <DashboardSectionCard
      {...UPCOMING_DATES_SECTION}
      testId='upcoming-dates-card'
      placeholder={
        dates ? undefined : (
          <DashboardSectionPlaceholder
            pending={isPending}
            copy={UPCOMING_DATES_PLACEHOLDER_COPY}
            testIdPrefix='upcoming-dates'
          />
        )
      }
      footer={
        hasMore ? (
          <div className='mt-3 flex justify-center'>
            <Button
              variant='link'
              size='sm'
              className='text-muted-foreground'
              data-testid='upcoming-dates-show-more'
              onClick={() => setExpanded(true)}
            >
              {showAllLabel(upcoming?.total ?? total)}
            </Button>
          </div>
        ) : undefined
      }
    >
      {shown?.map((date, index) => (
        // No id travels with an occurrence — the payload carries the resolved
        // date, not the row it came from — so identity is composed from what
        // does. The index is appended because a contact can hold two custom
        // dates with the same name on one day, which is degenerate but not
        // impossible, and a duplicate key is a rendering bug.
        <UpcomingDateRow
          key={`${date.contact_id}:${date.date_type}:${date.custom_date_type_name ?? ''}:${date.occurs_on}:${index}`}
          date={date}
        />
      ))}
    </DashboardSectionCard>
  );
}
