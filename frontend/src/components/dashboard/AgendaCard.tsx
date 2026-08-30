/**
 * AgendaCard — today's schedule (**W11**).
 *
 * This phase ships the card's frame: its header, its labelled list and the
 * single line it shows when nothing is scheduled — the wireframe does not draw
 * that state (gap 1), so it is built in **W29**'s idiom. Today's entries land
 * in Phase 7 and the tomorrow disclosure in Phase 8, both inside this card.
 */

import { CalendarCheck, CalendarDays } from 'lucide-react';
import { DashboardSectionCard } from './DashboardSectionCard';

/** The section's wireframe copy, in one place so the page and its tests agree. */
export const AGENDA_SECTION = {
  icon: CalendarDays,
  iconChipClassName: 'bg-chart-1 text-white',
  title: 'Agenda',
  description: "Today's schedule in time order, all-day items first.",
  listLabel: "Today's agenda",
  emptyIcon: CalendarCheck,
  emptyMessage: 'Nothing scheduled today.',
} as const;

export function AgendaCard() {
  return <DashboardSectionCard {...AGENDA_SECTION} testId='agenda-card' />;
}
