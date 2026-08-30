/**
 * UpcomingDatesCard — important contact dates in the coming week (**W30**).
 *
 * This phase ships the card's frame: its header, its labelled list and the
 * single line it shows when the window holds nothing — undrawn by the
 * wireframe (gap 2), so built in **W29**'s idiom. The resolved occurrences and
 * the show-more land in Phase 12, inside this card.
 */

import { CalendarOff, Star } from 'lucide-react';
import { DashboardSectionCard } from './DashboardSectionCard';

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

export function UpcomingDatesCard() {
  return (
    <DashboardSectionCard
      {...UPCOMING_DATES_SECTION}
      testId='upcoming-dates-card'
    />
  );
}
