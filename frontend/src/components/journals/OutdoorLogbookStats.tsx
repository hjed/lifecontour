/**
 * OutdoorLogbookStats — the logbook dashboard's headline numbers.
 *
 * Four tiles above the widget grid, so the state of the logbook is readable
 * without scanning any list: how much needs attention, what is coming up, and
 * how much has actually been done lately.
 *
 * The two "logged" numbers come from the server's distinct counts rather than
 * being summed here: a journal recording two independent subtypes lands in two
 * per-type buckets while being one activity, and the templates_done done-counts
 * are all-time.
 *
 * Fetch failures are deliberately not surfaced here — every widget below owns
 * an error state for the same two queries, so a banner in this row would just
 * repeat them. A failed *initial* load has no cached data, so its tiles read
 * zero; a failed *refetch* keeps React Query's last-good data, so the tiles
 * hold their last-known values rather than flashing to zero on a transient
 * blip (the widgets below still show their error state).
 */

'use client';

import { AlertCircle, BookTemplate, MapPin, Mountain } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useOutdoorDashboard } from '@/lib/api/outdoor-dashboard';
import { useIncompleteOutdoorActivities } from '@/lib/api/incomplete-outdoor-activities';

interface StatTile {
  readonly key: string;
  readonly value: number;
  readonly label: string;
  readonly sub: string;
  readonly icon: React.ComponentType<{
    className?: string;
    'aria-hidden'?: boolean | 'true' | 'false';
  }>;
}

export function OutdoorLogbookStats() {
  const dashboard = useOutdoorDashboard();
  // Always the undismissed list: this row counts what still needs attention,
  // independently of the widget's own "show dismissed" switch.
  const incomplete = useIncompleteOutdoorActivities(false);

  const attributes = dashboard.data?.data.attributes;
  const needsAttention = (incomplete.data?.data ?? []).filter(
    entry => !entry.attributes.dismissed
  ).length;

  const tiles: StatTile[] = [
    {
      key: 'incomplete',
      value: needsAttention,
      label: 'Incomplete activities',
      sub: 'need attention',
      icon: AlertCircle,
    },
    {
      key: 'upcoming',
      value: attributes?.upcoming_activities.length ?? 0,
      label: 'Upcoming',
      // The API caps the list at 10, so the tile says so rather than
      // implying 10 is ever the true total.
      sub: 'next 30 days (up to 10)',
      icon: MapPin,
    },
    {
      key: 'templates',
      value: attributes?.templates_done_last_30_days ?? 0,
      label: 'Templates done',
      sub: 'unique, last 30 days',
      icon: BookTemplate,
    },
    {
      key: 'activities',
      value: attributes?.activity_totals.total_last_30_days ?? 0,
      label: 'Activities logged',
      sub: 'last 30 days',
      icon: Mountain,
    },
  ];

  if (dashboard.isLoading || incomplete.isLoading) {
    return (
      <div
        className='grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4'
        data-testid='logbook-stats-loading'
      >
        {tiles.map(tile => (
          <Skeleton key={tile.key} className='h-[104px] w-full' />
        ))}
      </div>
    );
  }

  return (
    <div
      className='grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4'
      data-testid='logbook-stats-ready'
    >
      {tiles.map(({ key, value, label, sub, icon: Icon }) => (
        <Card key={key} data-testid={`logbook-stat-${key}`}>
          <CardContent className='flex items-start justify-between gap-3 p-4'>
            <div className='min-w-0'>
              <p
                className='text-foreground text-3xl leading-none font-bold tabular-nums'
                data-testid='stat-value'
              >
                {value}
              </p>
              <p className='text-foreground mt-2 text-sm font-semibold'>
                {label}
              </p>
              <p className='text-muted-foreground mt-0.5 text-xs'>{sub}</p>
            </div>
            <Icon
              className='text-muted-foreground h-[18px] w-[18px] shrink-0'
              aria-hidden='true'
            />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
