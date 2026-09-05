/**
 * AgendaEntryRow — one event journal as the agenda draws it (**W12**–**W18**).
 *
 * A bordered rounded row with a coloured accent bar down its left edge and a
 * hover shadow (**W17**) — the row idiom the task row shares — holding the
 * title as a link to the journal behind a calendar glyph (**W14**), the clock
 * range in tabular figures with the location beside it (**W13**) or the
 * **ALL DAY** marker in its place (**W12**), the tags as outline badges in
 * their own colours (**W15**) and the participants as an avatar stack
 * (**W16**).
 *
 * A pure function of the payload entry, with no query of its own, so the same
 * row renders today's list and tomorrow's, inside the disclosure beneath it.
 *
 * **A cancelled entry is shown, not hidden, and never as if still happening**
 * (**W18**): the whole row is dimmed, the accent bar is muted rather than
 * drawn in the calendar's colour, the title is struck through, and a bold
 * **CANCELLED** badge sits beside it — visible text, so assistive technology
 * gets the same signal without extra ARIA.
 *
 * **Two things the wireframe draws that this row deliberately does not.** W14
 * shows a second glyph for the journal's type; the payload carries no journal
 * types, and joining them is a payload change a card phase must not make, so
 * only the calendar glyph is drawn (recorded as a wireframe gap). And the
 * clock values are the *event's* wall time in its own zone, exactly as the
 * calendar views render them; the zone is not shown.
 */

import Link from 'next/link';
import type { Route } from 'next';
import { CalendarDays, Clock } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { formatClockRange } from '@/lib/agenda-display';
import type { HomeDashboardAgendaEntry } from '@/lib/api/home-dashboard';
import { cn } from '@/lib/utils';
import { AgendaParticipantStack } from './AgendaParticipantStack';

interface AgendaEntryRowProps {
  readonly entry: HomeDashboardAgendaEntry;
}

export function AgendaEntryRow({ entry }: AgendaEntryRowProps) {
  const clock = entry.is_all_day
    ? null
    : formatClockRange(entry.start_time, entry.end_time);

  return (
    <li
      data-testid={`agenda-entry-${entry.journal_id}`}
      className={cn(
        'border-border relative overflow-hidden rounded-lg border py-3 pr-3 pl-4 transition-shadow hover:shadow-sm',
        entry.is_cancelled && 'opacity-60'
      )}
    >
      <AccentBar color={entry.calendar_color} cancelled={entry.is_cancelled} />

      <div className='flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1'>
        <CalendarDays
          className='text-muted-foreground h-4 w-4 shrink-0'
          aria-hidden='true'
        />
        <Link
          href={`/journals/${entry.journal_id}` as Route}
          className={cn(
            'min-w-0 font-medium underline-offset-4 hover:underline',
            entry.is_cancelled && 'text-muted-foreground line-through'
          )}
        >
          {entry.title}
        </Link>
        {entry.is_all_day && (
          <span
            data-testid='agenda-entry-all-day'
            className='text-muted-foreground text-xs font-semibold tracking-wider uppercase'
          >
            All day
          </span>
        )}
        {entry.is_cancelled && (
          <Badge
            variant='outline'
            data-testid='agenda-entry-cancelled'
            className='text-muted-foreground text-[10px] font-bold tracking-wider uppercase'
          >
            Cancelled
          </Badge>
        )}
      </div>

      {(clock || entry.location) && (
        <p className='text-muted-foreground mt-1 flex min-w-0 flex-wrap items-center gap-x-1.5 text-sm'>
          {clock && (
            <>
              <Clock className='h-3.5 w-3.5 shrink-0' aria-hidden='true' />
              <span data-testid='agenda-entry-time' className='tabular-nums'>
                {clock}
              </span>
            </>
          )}
          {clock && entry.location && <span aria-hidden='true'>·</span>}
          {entry.location && (
            <span data-testid='agenda-entry-location' className='min-w-0'>
              {entry.location}
            </span>
          )}
        </p>
      )}

      {(entry.tags.length > 0 || entry.participants.length > 0) && (
        <div className='mt-2 flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-2'>
          {entry.tags.length > 0 && (
            <div
              data-testid='agenda-entry-tags'
              className='flex min-w-0 flex-wrap gap-1'
            >
              {entry.tags.map(tag => (
                <Badge
                  key={tag.id}
                  variant='outline'
                  style={
                    tag.color
                      ? { borderColor: tag.color, color: tag.color }
                      : undefined
                  }
                >
                  {tag.name}
                </Badge>
              ))}
            </div>
          )}
          <AgendaParticipantStack participants={entry.participants} />
        </div>
      )}
    </li>
  );
}

interface AccentBarProps {
  readonly color: string | null;
  readonly cancelled: boolean;
}

/**
 * The left accent bar (**W17**), keyed to the calendar's colour.
 *
 * Inline style rather than a class: the colour is a runtime hex value and
 * Tailwind cannot generate a class for it. The section's own chart colour
 * stands in when the calendar has none, and a cancelled row gets a muted bar
 * instead of its calendar colour (**W18**).
 */
function AccentBar({ color, cancelled }: AccentBarProps) {
  const inlineColor = !cancelled && color ? { backgroundColor: color } : null;
  return (
    <span
      aria-hidden='true'
      data-testid='agenda-entry-accent'
      className={cn(
        'absolute inset-y-0 left-0 w-1',
        cancelled && 'bg-muted-foreground/40',
        !cancelled && !color && 'bg-chart-1'
      )}
      {...(inlineColor ? { style: inlineColor } : {})}
    />
  );
}
