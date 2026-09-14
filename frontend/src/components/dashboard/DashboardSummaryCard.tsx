/**
 * DashboardSummaryCard — the dashboard's headline (**W5**–**W10**).
 *
 * Today's AI daily summary: the **same** entity the journals view shows for
 * today, read from the dashboard payload the page already fetched. The summary
 * section is a plain read of that row; the one time the card goes to the
 * daily-summary endpoint itself is to obtain a summary the payload does not
 * have, below.
 *
 * The card is drawn apart from the three evidence cards below it (**W5**): a
 * primary tint and a primary accent bar down its left edge, so the headline
 * reads as the headline rather than as a fourth section.
 *
 * Three declared states and no fourth (**W33**): generated (**W7**), generating
 * (**W8**), and unavailable (**W9**) — which covers "there is none today" as
 * well as "it could not be read", because a summary is not a list and so has no
 * empty state. **W6**'s Regenerate control sits *outside* all three branches
 * and is usable in every one of them whenever a summary is not already on its
 * way.
 *
 * There is one rendering the wireframe does not declare: what the card shows
 * while the page's query is still in flight. Wireframe gap 9 anticipates it —
 * no per-section loading state is depicted, and each section needs one — and
 * Phase 16 draws it as a skeleton of the prose that is coming. It is not a
 * fourth *state*, since nothing on the wire produces it: **W9** still covers
 * every way the card can end up with no summary once the read has landed.
 *
 * **The card reads today's summary on load, and never forces one.** The
 * dashboard's own read does not generate, so after an invalidation or on a new
 * day it reports *generating* with nothing generating it. Once per mount and anchor day,
 * when that first settled read has no prose, the card reads today's summary —
 * the read that regenerates a missing, invalidated or stale one — and reads the
 * dashboard back (`useObtainTodaySummaryOnLoad`, ITER18-005 Phase 8). That is
 * the specification's "the summary refreshes on the next load". Regenerate is
 * busy while it happens, and pressing it stays the only way to *force* one.
 *
 * **A summary the card has drawn is held for the visit.** A task ticked off
 * here invalidates today's summary on the server, so the tick's own refetch
 * reports it *generating*; taking the prose off the screen then would be
 * regenerating underneath a reader who only ticked a task. So a generated
 * summary stays drawn — prose, key stats and no badge — until a newer one
 * arrives or the anchor day moves on, and the next load brings the refreshed
 * one. Withholding stale prose is still the rule for what a *load* receives:
 * the hold only keeps what this visit has already drawn as current.
 */

'use client';

import { RefreshCw, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { DashboardSectionBoundary } from './DashboardSectionBoundary';
import { SummaryKeyStats } from './SummaryKeyStats';
import {
  DashboardSectionStatus,
  DashboardSummaryState,
  isSettledDashboardRead,
  useHomeDashboard,
} from '@/lib/api/home-dashboard';
import type { HomeDashboardSummary } from '@/lib/api/home-dashboard';
import { useRegenerateDailySummary } from '@/lib/api/journals';
import { useObtainTodaySummaryOnLoad } from '@/lib/api/today-summary-on-load';
import { isAnchorStillToday } from '@/lib/dashboard-anchor';
import { cn } from '@/lib/utils';

const HEADING_ID = 'dashboard-summary-heading';

/** The card's wireframe copy, in one place so the card and its tests agree. */
const SUMMARY_COPY = {
  label: 'AI Daily Summary',
  regenerate: 'Regenerate',
  generatingBadge: 'Generating...',
  generatingBody: 'Summary is being generated...',
  loading: "Loading today's summary...",
  /**
   * **W9** words this as "AI summaries are not configured", but *unavailable*
   * also covers a day that simply has no summary yet, which is the ordinary
   * case. Naming a cause the card cannot know would be wrong more often than
   * it was right, so only the cause clause is dropped; **W9**'s reassurance —
   * the part that matters — is kept verbatim.
   */
  unavailable: 'No summary today — everything below still works.',
} as const;

/**
 * The headline as the page mounts it: the card behind the boundary that keeps a
 * malformed summary from taking the rest of the page with it.
 *
 * The card is the one part of the page that renders free prose and a row of
 * derived counters, which is where a payload that broke its contract actually
 * throws — `summary_text` arriving as anything but a string, say, or a mood
 * value the stats row cannot format. The fallback is the same frame carrying
 * **W9**'s line, without the Regenerate control: the day to post to is read
 * from the very payload that could not be drawn.
 */
export function DashboardSummaryCard() {
  return (
    <DashboardSectionBoundary fallback={<DashboardSummaryUnavailable />}>
      <DashboardSummaryCardBody />
    </DashboardSectionBoundary>
  );
}

/** The frame both the card and its fallback are drawn in (**W5**, **W6**). */
function SummaryCardFrame({
  children,
}: {
  readonly children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={HEADING_ID}>
      <Card
        className='bg-primary/5 border-primary/20 border-l-primary border-l-4'
        data-testid='dashboard-summary-card'
      >
        <CardContent className='flex flex-col gap-3 p-4'>
          {children}
        </CardContent>
      </Card>
    </section>
  );
}

interface SummaryCardHeaderProps {
  readonly isGenerating: boolean;
  /** The Regenerate control, where there is a day it could act on. */
  readonly actions?: React.ReactNode;
}

/** The label row (**W6**), shared so the fallback cannot drift from the card. */
function SummaryCardHeader({ isGenerating, actions }: SummaryCardHeaderProps) {
  return (
    <div className='flex items-center justify-between gap-2'>
      <div className='text-primary flex min-w-0 items-center gap-2'>
        <span className='bg-primary/10 flex h-8 w-8 shrink-0 items-center justify-center rounded-md'>
          <Sparkles className='h-4 w-4' aria-hidden='true' />
        </span>
        <h2 id={HEADING_ID} className='text-sm font-semibold'>
          {SUMMARY_COPY.label}
        </h2>
        {isGenerating && (
          <Badge variant='secondary' className='text-xs'>
            {SUMMARY_COPY.generatingBadge}
          </Badge>
        )}
      </div>
      {actions}
    </div>
  );
}

/**
 * The card with nothing in it but **W9**'s line — the boundary's fallback.
 *
 * No Regenerate: the control posts `meta.anchor.date`, and a card that threw
 * rendering this payload has no anchor it can be trusted to have read. That is
 * the same "a wrong date is worse than none" rule the page header follows.
 */
function DashboardSummaryUnavailable() {
  return (
    <SummaryCardFrame>
      <SummaryCardHeader isGenerating={false} />
      <p
        className='text-muted-foreground text-sm'
        data-testid='dashboard-summary-unavailable'
      >
        {SUMMARY_COPY.unavailable}
      </p>
    </SummaryCardFrame>
  );
}

function DashboardSummaryCardBody() {
  const { data, isPending, isFetching, isSuccess, isFetchedAfterMount } =
    useHomeDashboard();
  const { mutate: regenerate, isPending: isRegenerating } =
    useRegenerateDailySummary();
  const { isObtaining } = useObtainTodaySummaryOnLoad();

  const anchor = data?.meta.anchor;
  // Only regenerate a day the anchor still agrees is today — a dashboard held
  // open across local midnight would otherwise rewrite yesterday's summary
  // under a page headed "Today". See `isAnchorStillToday`.
  const anchorDate =
    anchor && isAnchorStillToday(anchor) ? anchor.date : undefined;
  const section = data?.data.attributes.summary;
  const summary =
    section?.status === DashboardSectionStatus.READY ? section.data : null;

  // A generated summary with no text is not a state the wire declares, so it
  // falls through to W9 rather than drawing an empty paragraph.
  const generated =
    summary?.state === DashboardSummaryState.GENERATED && summary.summary_text
      ? summary
      : null;
  const shown = useHeldSummary(
    anchor?.date,
    generated,
    isSettledDashboardRead({ isSuccess, isFetching, isFetchedAfterMount })
  );
  const prose = shown?.summary_text ?? null;
  // While the card obtains today's summary, one is being generated, whatever the
  // first read said: a new day's first load has no row at all, which reads as
  // unavailable, and W9's "No summary today" beside a busy Regenerate would say
  // the opposite of what is happening.
  const isGenerating =
    !shown &&
    (isObtaining || summary?.state === DashboardSummaryState.GENERATING);
  // Busy for the reader's own regeneration and for the card's read on load
  // alike: either way a summary is on its way, and a press would ask twice.
  const isBusy = isRegenerating || isObtaining;

  const handleRegenerate = () => {
    // Re-checked at click time, not just at render. The button's disabled state
    // is computed while React renders, and a dashboard left mounted across
    // local midnight need never render again — so the enabled button would
    // still be closing over yesterday's anchor, which is the exact write this
    // guard exists to prevent.
    if (anchor && isAnchorStillToday(anchor)) {
      regenerate(anchor.date);
    }
  };

  return (
    <SummaryCardFrame>
      <SummaryCardHeader
        isGenerating={isGenerating}
        actions={
          <>
            {/* Outside the state branches below, per W6: it is the action that
                resolves W8's dead end and W9's absence alike.

                Disabled while a summary is already on its way — the reader's own
                regeneration or the card's read on load — or while there is no
                anchor day to post to. The second case is the page's first load
                — but it is also a dashboard request that *failed*, where the
                card shows W9 beside a control it cannot use. That is the least
                wrong answer available: the day to regenerate is the server's
                today in the user's configured zone, and posting the browser's
                instead would regenerate the wrong day for anyone whose zone
                differs, which is the same "a wrong date is worse than none"
                rule the page header follows. Recovering a failed *request* is
                a retry, not a regeneration, and belongs to Phase 16 with the
                other whole-page resilience.

                The same disabling covers a *stale* anchor — see
                `isAnchorStillToday`: a dashboard held open across local midnight
                would otherwise regenerate yesterday under a page headed
                "Today". */}
            <Button
              variant='ghost'
              size='sm'
              className='text-muted-foreground hover:text-primary shrink-0 gap-2'
              onClick={handleRegenerate}
              disabled={!anchorDate || isBusy}
              aria-busy={isBusy}
              data-testid='dashboard-summary-regenerate'
            >
              <RefreshCw
                className={cn(
                  'h-4 w-4 motion-reduce:animate-none',
                  isBusy && 'animate-spin'
                )}
                aria-hidden='true'
              />
              {SUMMARY_COPY.regenerate}
            </Button>
          </>
        }
      />

      {/* Deliberately **not** an `aria-live` region. The change worth
              announcing is the one the reader asked for, and the regeneration
              already announces itself through the toast — which is a live
              region. Marking the body live would announce it a second time,
              and, worse, would read the whole AI summary aloud unbidden on
              every page load, because the body's first content change is
              "loading" giving way to prose on a page this iteration makes the
              post-sign-in default. */}
      <SummaryBody
        isPending={isPending}
        isGenerating={isGenerating}
        prose={prose}
      />

      {/* W10 renders in the generated state only. The counters ride in the
          payload either way; where they are drawn is the card's call. */}
      {shown && (
        <SummaryKeyStats
          journalCount={shown.journal_count}
          eventCount={shown.event_count}
          contactCount={shown.contact_count}
          moodAverage={shown.mood_average}
        />
      )}
    </SummaryCardFrame>
  );
}

/**
 * The generated summary to draw: this read's, or — when this read withholds
 * one — the last one drawn for the same anchor day.
 *
 * Held in state, and updated while rendering, because it *is* information from
 * a previous render: what the reader has already been shown. Keyed on the
 * payload's anchor day, so a summary drawn for yesterday is never held over a
 * page that has moved on to today.
 *
 * **Only a settled read establishes it.** On client-side navigation back to the
 * page, React Query renders the previous visit's cached payload while the mount
 * refetch replaces it; a summary seen only there was never current on this
 * visit, and holding it would keep that prose over the server's answer that
 * today is stale. A hold established earlier is untouched while a later read is
 * in flight — which is exactly a task tick's refetch.
 */
function useHeldSummary(
  day: string | undefined,
  generated: HomeDashboardSummary | null,
  settled: boolean
): HomeDashboardSummary | null {
  const [held, setHeld] = useState<{
    readonly day: string;
    readonly summary: HomeDashboardSummary;
  } | null>(null);

  if (
    settled &&
    day &&
    generated &&
    (held?.day !== day || held.summary !== generated)
  ) {
    setHeld({ day, summary: generated });
  }

  if (generated) {
    return generated;
  }
  return held && held.day === day ? held.summary : null;
}

/**
 * Split the summary on blank lines, dropping any run of empty ones.
 *
 * A model that emits no blank line yields one paragraph, which is the common
 * case and exactly what W7's "one **or more**" allows.
 */
function paragraphsOf(prose: string): string[] {
  return prose
    .split(/\n\s*\n/)
    .map(paragraph => paragraph.trim())
    .filter(Boolean);
}

interface SummaryBodyProps {
  readonly isPending: boolean;
  readonly isGenerating: boolean;
  readonly prose: string | null;
}

function SummaryBody({ isPending, isGenerating, prose }: SummaryBodyProps) {
  if (isPending) {
    // Bars in the shape of the paragraph that is arriving, not a row skeleton:
    // the summary is prose (W7), and a skeleton is a promise about what is
    // coming. `aria-busy` with the sentence visually hidden, for the reason
    // the sections' skeleton gives and this card gave first — a live region
    // here would read out on every load of the post-sign-in page.
    return (
      <div
        aria-busy='true'
        className='space-y-2'
        data-testid='dashboard-summary-loading'
      >
        <span className='sr-only'>{SUMMARY_COPY.loading}</span>
        <Skeleton aria-hidden='true' className='h-4 w-full' />
        <Skeleton aria-hidden='true' className='h-4 w-full' />
        <Skeleton aria-hidden='true' className='h-4 w-2/3' />
      </div>
    );
  }

  if (isGenerating) {
    return (
      <p
        className='text-muted-foreground text-sm'
        data-testid='dashboard-summary-generating'
      >
        {SUMMARY_COPY.generatingBody}
      </p>
    );
  }

  if (prose) {
    // W7 asks for "one or more prose paragraphs", so a blank line in the
    // model's output becomes a real `<p>` rather than a bare line break inside
    // one: that is what gives the paragraphs spacing, and what lets a screen
    // reader move between them. `whitespace-pre-line` stays for the single
    // newlines *within* a paragraph. No clamp and no truncation — in full.
    return (
      <div
        className='space-y-2 text-sm leading-relaxed'
        data-testid='dashboard-summary-text'
      >
        {paragraphsOf(prose).map(paragraph => (
          <p key={paragraph} className='break-words whitespace-pre-line'>
            {paragraph}
          </p>
        ))}
      </div>
    );
  }

  return (
    <p
      className='text-muted-foreground text-sm'
      data-testid='dashboard-summary-unavailable'
    >
      {SUMMARY_COPY.unavailable}
    </p>
  );
}
