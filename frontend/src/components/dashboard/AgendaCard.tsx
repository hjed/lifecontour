/**
 * AgendaCard — today's schedule (**W11**–**W18**).
 *
 * Today's event journals, read from the dashboard payload the page already
 * fetched: the card calls `useHomeDashboard()` itself, the arrangement the
 * summary card established, so it owns its own loading and unavailable
 * renderings and still costs the page nothing — every caller shares one query
 * key and dedupes into a single request.
 *
 * **The card draws the list it is given and does not re-sort it.** All-day
 * entries first, then timed ones ascending by start, is the server's rule
 * (Phase 5a) and is pinned there; a second copy here would be a second place
 * for the two to disagree. Each entry is one `AgendaEntryRow`, the same row
 * the tomorrow disclosure reuses in the next phase.
 *
 * Three things the list can hold nothing for, and they are kept apart on
 * purpose: **nothing scheduled** is a real answer and gets the single
 * **W29**-idiom line the wireframe does not draw (gap 1); the query still
 * being **in flight** and the section coming back **unavailable** each get a
 * quiet line of their own, in **W9**'s idiom, so neither can be mistaken for a
 * clear day. The proper loading skeleton and unavailable treatment are Phase
 * 16's (wireframe gap 9); these are the placeholders until then, as the
 * summary card's were.
 */

'use client';

import { CalendarCheck, CalendarDays } from 'lucide-react';
import { AgendaEntryRow } from './AgendaEntryRow';
import { DashboardSectionCard } from './DashboardSectionCard';
import {
  DashboardSectionStatus,
  useHomeDashboard,
} from '@/lib/api/home-dashboard';

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

/** What the card says while it has no list to draw. Not shell props. */
const AGENDA_PLACEHOLDER_COPY = {
  loading: "Loading today's agenda...",
  unavailable: "Today's agenda is unavailable.",
} as const;

export function AgendaCard() {
  const { data, isPending } = useHomeDashboard();

  const section = data?.data.attributes.agenda;
  const agenda =
    section?.status === DashboardSectionStatus.READY ? section.data : null;

  return (
    <DashboardSectionCard
      {...AGENDA_SECTION}
      testId='agenda-card'
      placeholder={
        agenda ? undefined : <AgendaPlaceholder pending={isPending} />
      }
    >
      {agenda?.entries.map(entry => (
        <AgendaEntryRow key={entry.journal_id} entry={entry} />
      ))}
    </DashboardSectionCard>
  );
}

interface AgendaPlaceholderProps {
  readonly pending: boolean;
}

/**
 * What the card says while it has no list to draw: still loading, or the
 * section is unavailable — which also covers a dashboard request that failed
 * outright, where there is no envelope at all.
 */
function AgendaPlaceholder({ pending }: AgendaPlaceholderProps) {
  return pending ? (
    <p className='text-muted-foreground text-sm' data-testid='agenda-loading'>
      {AGENDA_PLACEHOLDER_COPY.loading}
    </p>
  ) : (
    <p
      className='text-muted-foreground text-sm'
      data-testid='agenda-unavailable'
    >
      {AGENDA_PLACEHOLDER_COPY.unavailable}
    </p>
  );
}
