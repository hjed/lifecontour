/**
 * TasksCard — what is due in the coming week (**W21**).
 *
 * This phase ships the card's frame: its header, its labelled list and
 * **W29**'s empty line, which the wireframe does draw for this section — one
 * muted sentence that reads as a good outcome rather than an error. The rows,
 * their inline done action and the show-more land in Phases 14 and 15, inside
 * this card.
 */

import { CheckCircle2, ClipboardList } from 'lucide-react';
import { DashboardSectionCard } from './DashboardSectionCard';

/** The section's wireframe copy, in one place so the page and its tests agree. */
export const TASKS_SECTION = {
  icon: ClipboardList,
  iconChipClassName: 'bg-chart-2 text-white',
  title: 'Tasks',
  description: 'Due in the next seven days, soonest first. Tick them off here.',
  listLabel: 'Tasks due in the next seven days',
  emptyIcon: CheckCircle2,
  emptyMessage: 'Nothing due in the next seven days.',
} as const;

export function TasksCard() {
  return <DashboardSectionCard {...TASKS_SECTION} testId='tasks-card' />;
}
