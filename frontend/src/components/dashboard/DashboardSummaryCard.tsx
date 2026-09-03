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
 * empty state.
 *
 * There is one rendering the wireframe does not declare: a quiet line while the
 * page's query is still in flight. Wireframe gap 9 anticipates it — no
 * per-section loading state is depicted, and each section needs one — and gives
 * Phase 16 the skeletons; this is the placeholder until then, built in **W9**'s
 * one-quiet-line idiom rather than as a fourth *state*, since nothing on the
 * wire produces it.
 *
 * **W6**'s Regenerate control lands in Phase 4c, which also settles what this
 * card does — and deliberately does not do — when the summary reports itself
 * generating with nothing generating it. This phase renders the states; that
 * one adds the only action the card will ever offer.
 */

'use client';

import { Sparkles } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { SummaryKeyStats } from './SummaryKeyStats';
import {
  DashboardSectionStatus,
  DashboardSummaryState,
  useHomeDashboard,
} from '@/lib/api/home-dashboard';

const HEADING_ID = 'dashboard-summary-heading';

/** The card's wireframe copy, in one place so the card and its tests agree. */
const SUMMARY_COPY = {
  label: 'AI Daily Summary',
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

export function DashboardSummaryCard() {
  const { data, isPending } = useHomeDashboard();

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

  return (
    <section aria-labelledby={HEADING_ID}>
      <Card
        className='bg-primary/5 border-primary/20 border-l-primary border-l-4'
        data-testid='dashboard-summary-card'
      >
        <CardContent className='flex flex-col gap-3 p-4'>
          <div className='flex items-center gap-2'>
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
          </div>

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
        </CardContent>
      </Card>
    </section>
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
    return (
      <p
        className='text-muted-foreground text-sm'
        data-testid='dashboard-summary-loading'
      >
        {SUMMARY_COPY.loading}
      </p>
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
          <p key={paragraph} className='whitespace-pre-line'>
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
