/**
 * SummaryKeyStats — the summary card's key-stats footer (**W10**).
 *
 * A top-bordered row of four label/value pairs — Journals, Events, Contacts and
 * Avg Mood — drawn from counters the daily summary entity already carries. It
 * is additive surfacing of existing data rather than a new computation, which
 * is why the wireframe asks for it and the specification does not mention it.
 *
 * A `dl` rather than four stacked `div`s: these are label/value pairs, and the
 * `dt`/`dd` pairing is what lets a screen reader read "Avg Mood, 7.5/10" as one
 * fact instead of two adjacent strings.
 *
 * All four pairs are always drawn, including a count of zero. The journals
 * view suppresses zeroes; this one does not, because a footer whose columns
 * appear and disappear with the data changes shape from day to day, and "no
 * events today" is worth reading rather than inferring from a gap. Whether the
 * footer is drawn *at all* is the card's decision — **W10** says the generated
 * state only.
 */

interface SummaryKeyStatsProps {
  readonly journalCount: number;
  readonly eventCount: number;
  readonly contactCount: number;
  /** Out of ten, or null when nothing was rated — which is most days. */
  readonly moodAverage: number | null;
}

export function SummaryKeyStats({
  journalCount,
  eventCount,
  contactCount,
  moodAverage,
}: SummaryKeyStatsProps) {
  // An em dash rather than `0`: nothing was rated, which is not the same as a
  // day rated zero.
  const mood = moodAverage === null ? '—' : `${moodAverage.toFixed(1)}/10`;

  const pairs: readonly (readonly [string, string])[] = [
    ['Journals', String(journalCount)],
    ['Events', String(eventCount)],
    ['Contacts', String(contactCount)],
    ['Avg Mood', mood],
  ];

  return (
    <dl
      className='border-primary/20 mt-1 grid grid-cols-2 gap-3 border-t pt-3 sm:grid-cols-4'
      data-testid='dashboard-summary-stats'
    >
      {pairs.map(([label, value]) => (
        // `min-w-0` so a long value wraps inside its column rather than
        // widening the card and pushing the page off screen (W3).
        <div key={label} className='flex min-w-0 flex-col'>
          <dt className='text-muted-foreground text-xs tracking-wider uppercase'>
            {label}
          </dt>
          <dd className='text-sm font-medium'>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
