/**
 * DashboardSummaryCard — the dashboard's headline (**W5**–**W10**).
 *
 * Today's AI daily summary: the **same** entity the journals view shows for
 * today, read from the dashboard payload the page already fetched rather than
 * from the daily-summary endpoint. That is deliberate — the journals view goes
 * through `DailySummaryService.get_or_generate`, which writes and can hold an
 * AI call open for seconds, and the specification makes this page a read-only
 * projection. The summary section is a plain read of the same row.
 *
 * The card is drawn apart from the three evidence cards below it (**W5**): a
 * primary tint and a primary accent bar down its left edge, so the headline
 * reads as the headline rather than as a fourth section.
 *
 * Three declared states and no fourth (**W33**): generated (**W7**), generating
 * (**W8**), and unavailable (**W9**) — which covers "there is none today" as
 * well as "it could not be read", because a summary is not a list and so has no
 * empty state. **W6**'s Regenerate control sits *outside* all three branches
 * and stays enabled in every one of them.
 *
 * There is one rendering the wireframe does not declare: what the card shows
 * while the page's query is still in flight. Wireframe gap 9 anticipates it —
 * no per-section loading state is depicted, and each section needs one — and
 * Phase 16 draws it as a skeleton of the prose that is coming. It is not a
 * fourth *state*, since nothing on the wire produces it: **W9** still covers
 * every way the card can end up with no summary once the read has landed.
 *
 * **Regeneration is never automatic.** Nothing currently moves a journal daily
 * summary out of `pending`, so a user who edits today's journal can see **W8**
 * with nothing generating behind it — and the tempting fix is for this card to
 * fire the regenerate endpoint when it sees `generating`. It does not: the page
 * every sign-in lands on must not start a multi-second AI write on load, and
 * the specification allows exactly two mutations here, the inline task action
 * and a *user-requested* regeneration. The Regenerate control is what resolves
 * that state, which is why it stays enabled inside it. Making the state honest
 * on read belongs to ITER18-005, which owns summary freshness.
 */

'use client';

import { RefreshCw, Sparkles } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { DashboardSectionBoundary } from './DashboardSectionBoundary';
import { SummaryKeyStats } from './SummaryKeyStats';
import {
  DashboardSectionStatus,
  DashboardSummaryState,
  useHomeDashboard,
} from '@/lib/api/home-dashboard';
import type { HomeDashboardAnchor } from '@/lib/api/home-dashboard';
import { useRegenerateDailySummary } from '@/lib/api/journals';
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
 * Whether the cached anchor is still the day it claims to be.
 *
 * The dashboard query has one fixed key and the app-wide `staleTime` is five
 * minutes, with no refetch scheduled at the day boundary — a dashboard left
 * open and focused across local midnight keeps yesterday's anchor. Phase 3
 * recorded that as a follow-up owned by Phase 16, when the only consequence was
 * a stale *label*.
 *
 * A **write** keyed on that anchor is a different matter: regenerating would
 * rewrite yesterday's summary while the page says "Today". So the action checks
 * the anchor against the wall clock in the zone the payload itself names, and
 * declines rather than guessing — which leaves the control disabled until the
 * query refetches, exactly as it is before the first load arrives.
 *
 * The comparison is built from `formatToParts` rather than `format`, because
 * `format` returns *presentation* output: which separator a locale uses is
 * CLDR data, not a guarantee, so a locale that renders `en-CA` with slashes
 * would make every comparison false and disable the control on a perfectly
 * current anchor. Reading the year, month and day parts and assembling
 * `YYYY-MM-DD` ourselves is locale-independent. The zone lookup is still
 * `Intl`'s, so there is no date arithmetic here and nothing for a DST
 * transition to catch out. Scheduling the refetch that *fixes* the staleness is
 * still Phase 16's; this only stops the write going to the wrong day.
 */
export function localDateIn(timeZone: string, now: Date): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find(candidate => candidate.type === type)?.value ?? '';

  return `${part('year')}-${part('month')}-${part('day')}`;
}

function isStillToday(anchor: HomeDashboardAnchor, now: Date = new Date()) {
  try {
    return localDateIn(anchor.timezone, now) === anchor.date;
  } catch {
    // An unrecognised zone would throw. The server resolved this day and the
    // browser cannot second-guess which one it meant, so trust the anchor.
    return true;
  }
}

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
  const { data, isPending } = useHomeDashboard();
  const { mutate: regenerate, isPending: isRegenerating } =
    useRegenerateDailySummary();

  const anchor = data?.meta.anchor;
  // Only regenerate a day the anchor still agrees is today. See `isStillToday`.
  const anchorDate = anchor && isStillToday(anchor) ? anchor.date : undefined;
  const section = data?.data.attributes.summary;
  const summary =
    section?.status === DashboardSectionStatus.READY ? section.data : null;

  // A generated summary with no text is not a state the wire declares, so it
  // falls through to W9 rather than drawing an empty paragraph.
  const prose =
    summary?.state === DashboardSummaryState.GENERATED
      ? summary.summary_text
      : null;
  const isGenerating = summary?.state === DashboardSummaryState.GENERATING;

  const handleRegenerate = () => {
    // Re-checked at click time, not just at render. The button's disabled state
    // is computed while React renders, and a dashboard left mounted across
    // local midnight need never render again — so the enabled button would
    // still be closing over yesterday's anchor, which is the exact write this
    // guard exists to prevent.
    if (anchor && isStillToday(anchor)) {
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

                Disabled only while it is already running, or while there is no
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
                `isStillToday`: a dashboard held open across local midnight
                would otherwise regenerate yesterday under a page headed
                "Today". */}
            <Button
              variant='ghost'
              size='sm'
              className='text-muted-foreground hover:text-primary shrink-0 gap-2'
              onClick={handleRegenerate}
              disabled={!anchorDate || isRegenerating}
              aria-busy={isRegenerating}
              data-testid='dashboard-summary-regenerate'
            >
              <RefreshCw
                className={cn('h-4 w-4', isRegenerating && 'animate-spin')}
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
      {prose && summary && (
        <SummaryKeyStats
          journalCount={summary.journal_count}
          eventCount={summary.event_count}
          contactCount={summary.contact_count}
          moodAverage={summary.mood_average}
        />
      )}
    </SummaryCardFrame>
  );
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
