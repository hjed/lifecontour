/**
 * TomorrowDisclosure — tomorrow beneath today, shut until asked (**W19**,
 * **W20**).
 *
 * The specification's reason for it is the evening: *"tomorrow appears beneath
 * today, collapsed by default, expandable in place... without turning it into
 * a calendar"*. So this is one row and one panel — no route, no navigation,
 * and no second way of drawing an event. Expanding maps tomorrow's entries
 * through the very `AgendaEntryRow` today's list uses, which is what "the same
 * information in the same form" has to mean if the two are never to drift.
 *
 * **The label comes from the server's day, never from the browser's.**
 * `agenda.tomorrow.date` is already resolved in the user's configured zone;
 * adding a day to the anchor here would be a second opinion about what
 * tomorrow is, and in a zone behind UTC it would be a wrong one.
 *
 * **The count includes cancelled entries**, because the list behind it shows
 * them (**W18** — shown, never hidden), and a count that disagreed with what
 * it opens onto would be worse than no count.
 *
 * **A clear tomorrow keeps its row**, counting none and opening onto one line.
 * Hiding the control would make "nothing on" indistinguishable from a
 * dashboard that had never looked.
 *
 * Accessibility follows the activity feed's precedent: a real button carrying
 * `aria-expanded` and `aria-controls` from Radix, over a `role="region"` named
 * by that button — so the name says *"Tomorrow — Saturday, 1 August, 2
 * events"* rather than making someone open it to find out whether it was worth
 * opening. Keyboard operation is structural, not handled here.
 */

'use client';

import { useId, useState } from 'react';
import { CalendarCheck, ChevronDown, ChevronRight } from 'lucide-react';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { WidgetEmptyState } from '@/components/journals/WidgetEmptyState';
import { formatEventCount } from '@/lib/agenda-display';
import { formatIsoWeekdayDate } from '@/lib/date-utils';
import type { HomeDashboardAgendaDay } from '@/lib/api/home-dashboard';
import { AgendaEntryRow } from './AgendaEntryRow';

/** The disclosure's copy, in one place so the row and its panel agree. */
const TOMORROW_COPY = {
  listLabel: "Tomorrow's agenda",
  emptyIcon: CalendarCheck,
  emptyMessage: 'Nothing scheduled tomorrow.',
} as const;

interface TomorrowDisclosureProps {
  /** Tomorrow as the server resolved it: its local date and its entries. */
  readonly day: HomeDashboardAgendaDay;
}

export function TomorrowDisclosure({ day }: TomorrowDisclosureProps) {
  const [isOpen, setIsOpen] = useState(false);
  const regionId = useId();

  // One string for the button's accessible name and the panel's: the visible
  // label and count are two elements for layout (W19 right-aligns the count),
  // but they are one sentence to anyone listening.
  const label = `Tomorrow — ${formatIsoWeekdayDate(day.date)}`;
  const count = formatEventCount(day.entries.length);
  const accessibleName = `${label}, ${count}`;

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen} className='mt-3'>
      <CollapsibleTrigger
        aria-label={accessibleName}
        aria-controls={regionId}
        data-testid='tomorrow-trigger'
        className='border-border hover:bg-muted/50 focus-visible:ring-ring flex w-full items-center gap-2 rounded-md border-t px-1 py-2 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none'
      >
        {isOpen ? (
          <ChevronDown
            className='text-muted-foreground h-4 w-4 shrink-0'
            aria-hidden='true'
            data-testid='tomorrow-chevron-open'
          />
        ) : (
          <ChevronRight
            className='text-muted-foreground h-4 w-4 shrink-0'
            aria-hidden='true'
            data-testid='tomorrow-chevron-closed'
          />
        )}
        {/* `min-w-0` so a long weekday wraps rather than pushing the count off
            the card at 375px (W3). */}
        <span
          className='min-w-0 flex-1 text-sm font-medium'
          data-testid='tomorrow-label'
        >
          {label}
        </span>
        <span
          className='text-muted-foreground shrink-0 text-sm'
          data-testid='tomorrow-count'
        >
          {count}
        </span>
      </CollapsibleTrigger>

      <CollapsibleContent
        id={regionId}
        role='region'
        aria-label={accessibleName}
        data-testid='tomorrow-panel'
      >
        {day.entries.length > 0 ? (
          <ul
            aria-label={TOMORROW_COPY.listLabel}
            className='min-w-0 space-y-3 pt-3'
          >
            {day.entries.map(entry => (
              <AgendaEntryRow key={entry.journal_id} entry={entry} />
            ))}
          </ul>
        ) : (
          <WidgetEmptyState
            icon={TOMORROW_COPY.emptyIcon}
            message={TOMORROW_COPY.emptyMessage}
            className='py-4'
            data-testid='tomorrow-empty'
          />
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}
