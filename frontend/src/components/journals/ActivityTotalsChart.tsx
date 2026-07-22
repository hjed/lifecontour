/**
 * ActivityTotalsChart — the dashboard's recent activity totals.
 *
 * Counts of the user's outdoor activities by journal type over two rolling
 * windows shown together: the last 30 days and the last 365 days. Types are
 * the effective (dependency-reduced) journal types computed server-side.
 *
 * Each row overlays the two windows on one track — the 365-day bar tinted
 * behind the solid 30-day bar — so recent activity reads against the year's
 * baseline at a glance. Every bar is scaled against the largest 365-day count
 * in the chart, so row heights are comparable rather than each row being
 * self-normalised.
 *
 * The bars are decoration: both counts are rendered as text (with a screen
 * reader-only qualifier naming the windows), so the widget carries the same
 * information without them.
 */

'use client';

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { Mountain } from 'lucide-react';
import {
  TYPE_ICONS,
  TYPE_LABELS,
} from '@/components/journals/JournalTypeBadges';
import { WidgetEmptyState } from '@/components/journals/WidgetEmptyState';
import {
  OutdoorActivityTotals,
  useOutdoorDashboard,
} from '@/lib/api/outdoor-dashboard';
import { JournalType } from '@/types/journals';

/** The sorted union of the types present in either window. */
function totalTypes(totals: OutdoorActivityTotals): JournalType[] {
  const keys = new Set([
    ...Object.keys(totals.last_30_days),
    ...Object.keys(totals.last_365_days),
  ]);
  return [...keys].sort((a, b) => a.localeCompare(b)) as JournalType[];
}

/**
 * The scale every bar is measured against — the largest 365-day count, which
 * is always ≥ the matching 30-day count since the windows nest.
 */
function chartMax(totals: OutdoorActivityTotals): number {
  const counts = Object.values(totals.last_365_days);
  return counts.length > 0 ? Math.max(...counts) : 0;
}

function barWidth(count: number, max: number): string {
  return `${max > 0 ? (count / max) * 100 : 0}%`;
}

export function ActivityTotalsChart() {
  const { data, isLoading, error } = useOutdoorDashboard();

  const totals = data?.data.attributes.activity_totals ?? {
    last_30_days: {},
    last_365_days: {},
    total_last_30_days: 0,
    total_last_365_days: 0,
  };
  const types = totalTypes(totals);
  const max = chartMax(totals);

  return (
    <Card className='flex flex-col'>
      <CardHeader>
        <CardTitle>Recent activity totals</CardTitle>
        <CardDescription>
          Outdoor activities by type over the rolling last 30 days and last 365
          days.
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-1 flex-col'>
        {isLoading && (
          <div className='space-y-4' data-testid='totals-loading'>
            <Skeleton className='h-8 w-full' />
            <Skeleton className='h-8 w-full' />
            <Skeleton className='h-8 w-full' />
          </div>
        )}

        {error && !isLoading && (
          <Alert variant='destructive' data-testid='totals-error'>
            <p>Failed to load activity totals: {error.message}</p>
          </Alert>
        )}

        {!isLoading && !error && (
          <div className='flex flex-1 flex-col' data-testid='totals-ready'>
            {types.length === 0 ? (
              <WidgetEmptyState
                icon={Mountain}
                message='No outdoor activity recorded in the last year.'
                data-testid='totals-empty-state'
              />
            ) : (
              <>
                <ul
                  className='space-y-3.5'
                  aria-label='Outdoor activity counts by type over the last 30 and 365 days'
                  data-testid='activity-totals-chart'
                >
                  {types.map(type => {
                    const Icon = TYPE_ICONS[type];
                    const label = TYPE_LABELS[type] ?? type;
                    const count30 = totals.last_30_days[type] ?? 0;
                    const count365 = totals.last_365_days[type] ?? 0;
                    return (
                      <li key={type} data-testid={`totals-row-${type}`}>
                        <div className='mb-1.5 flex items-center justify-between gap-2'>
                          <span className='flex min-w-0 items-center gap-1.5 text-sm'>
                            {Icon && (
                              <Icon
                                className='h-3.5 w-3.5 shrink-0'
                                aria-hidden='true'
                              />
                            )}
                            <span className='truncate'>{label}</span>
                          </span>
                          <span className='text-muted-foreground shrink-0 text-xs tabular-nums'>
                            {/* Visible "30 · 365"; hidden from assistive tech so
                                the counts aren't announced twice — the sr-only
                                sentence below carries them once, in context. */}
                            <span aria-hidden='true'>
                              <span
                                className='text-foreground font-semibold'
                                data-testid={`totals-30d-${type}`}
                              >
                                {count30}
                              </span>
                              {' · '}
                              <span data-testid={`totals-365d-${type}`}>
                                {count365}
                              </span>
                            </span>
                            <span className='sr-only'>
                              {`${count30} in the last 30 days, ${count365} in the last 365 days`}
                            </span>
                          </span>
                        </div>
                        <div
                          className='bg-muted relative h-1.5 w-full overflow-hidden rounded-full'
                          aria-hidden='true'
                        >
                          <div
                            className='bg-primary/30 absolute inset-y-0 left-0 rounded-full'
                            style={{ width: barWidth(count365, max) }}
                            data-testid={`totals-bar-365d-${type}`}
                          />
                          <div
                            className='bg-primary absolute inset-y-0 left-0 rounded-full'
                            style={{ width: barWidth(count30, max) }}
                            data-testid={`totals-bar-30d-${type}`}
                          />
                        </div>
                      </li>
                    );
                  })}
                </ul>
                <p
                  className='text-muted-foreground mt-4 flex items-center gap-4 text-xs'
                  aria-hidden='true'
                >
                  <span className='flex items-center gap-1.5'>
                    <span className='bg-primary h-2 w-2 rounded-full' />
                    Last 30 days
                  </span>
                  <span className='flex items-center gap-1.5'>
                    <span className='bg-primary/30 h-2 w-2 rounded-full' />
                    Last 365 days
                  </span>
                </p>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
