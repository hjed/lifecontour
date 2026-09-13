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
 * the tomorrow disclosure beneath it reuses.
 *
 * **Tomorrow hangs off the shell's footer, and only on a ready agenda**
 * (**W19**, **W20**): it is drawn from the payload's own `tomorrow` day, so a
 * section that has not answered has no count to state and no day to name, and
 * the control stays away rather than claiming "0 events" about a read that
 * never landed.
 *
 * Three things the list can hold nothing for, and they are kept apart on
 * purpose: **nothing scheduled** is a real answer and gets the single
 * **W29**-idiom line the wireframe does not draw (gap 1); the query still
 * being **in flight** gets the pulsing row skeleton and the section coming
 * back **unavailable** its own centred line, so neither can be mistaken for a
 * clear day. Both are `DashboardSectionPlaceholder`'s, which is where the
 * shape of the two states now lives; this card supplies only their wording.
 */

'use client';

import { CalendarCheck, CalendarDays } from 'lucide-react';
import { AgendaEntryRow } from './AgendaEntryRow';
import { DashboardSectionCard } from './DashboardSectionCard';
import { DashboardSectionPlaceholder } from './DashboardSectionPlaceholder';
import { TomorrowDisclosure } from './TomorrowDisclosure';
import {
  DashboardSectionStatus,
  useHomeDashboard,
} from '@/lib/api/home-dashboard';
import { isIsoCalendarDate } from '@/lib/date-utils';

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

  // Both fields the disclosure reads, each checked for what would actually
  // break it rather than for the one malformed shape last remembered: the type
  // promises a `tomorrow` carrying a formattable date *and* an entries array on
  // every ready agenda, but a payload that broke either half used to throw out
  // of render and take the *whole page* with it — the summary, the tasks and
  // the dates included. The specification's "sections render independently"
  // has to survive a section that breaks its contract, not only one that
  // reports itself unavailable, and a missing `tomorrow`, an absent list and an
  // unparseable date all fail identically from the reader's seat.
  //
  // This guards the two fields *this* card reads. Blanket protection against an
  // arbitrarily malformed section — a bad entry inside the list, say — wants an
  // error boundary around the section rather than a longer list of checks here,
  // and that is Phase 16's scope (Section Resilience).
  const tomorrow = agenda?.tomorrow;
  const hasTomorrow =
    isIsoCalendarDate(tomorrow?.date) && Array.isArray(tomorrow?.entries);

  return (
    <DashboardSectionCard
      {...AGENDA_SECTION}
      testId='agenda-card'
      placeholder={
        agenda ? undefined : (
          <DashboardSectionPlaceholder
            pending={isPending}
            copy={AGENDA_PLACEHOLDER_COPY}
            testIdPrefix='agenda'
          />
        )
      }
      footer={
        hasTomorrow && tomorrow ? (
          <TomorrowDisclosure day={tomorrow} />
        ) : undefined
      }
    >
      {agenda?.entries.map(entry => (
        <AgendaEntryRow key={entry.journal_id} entry={entry} />
      ))}
    </DashboardSectionCard>
  );
}
