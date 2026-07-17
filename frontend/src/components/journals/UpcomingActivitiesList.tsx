/**
 * UpcomingActivitiesList — the dashboard's upcoming outdoor activities.
 *
 * Lists the user's outdoor activities and planning events over the next
 * 30 days (soonest first, capped at 10 server-side), each linking to its
 * journal with its date range and type badges.
 */

'use client';

import Link from 'next/link';
import type { Route } from 'next';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { JournalTypeBadges } from '@/components/journals/JournalTypeBadges';
import {
  UpcomingOutdoorActivityEntry,
  useOutdoorDashboard,
} from '@/lib/api/outdoor-dashboard';
import { formatDateRange } from '@/lib/date-utils';
import { JournalType } from '@/types/journals';

/**
 * The badge types for an upcoming entry. Planning events carry no subtype
 * rows, so they get the Outdoor Planning badge; activity entries show their
 * raw subtype presence flags (dependency-added rows included, matching the
 * incomplete review), falling back to the generic Outdoor Activity badge for
 * subtype-less journals (mirroring the backend's effective-type fallback).
 */
function displayTypes(entry: UpcomingOutdoorActivityEntry): JournalType[] {
  if (entry.is_planning) {
    return [JournalType.OUTDOOR_PLANNING, ...entry.subtypes];
  }
  return entry.subtypes.length > 0
    ? entry.subtypes
    : [JournalType.OUTDOOR_ACTIVITY];
}

export function UpcomingActivitiesList() {
  const { data, isLoading, error } = useOutdoorDashboard();

  const entries = data?.data.attributes.upcoming_activities ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upcoming activities</CardTitle>
        <CardDescription>
          Your outdoor activities and planning events over the next 30 days,
          soonest first (up to 10).
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className='space-y-3' data-testid='upcoming-loading'>
            <Skeleton className='h-16 w-full' />
            <Skeleton className='h-16 w-full' />
          </div>
        )}

        {error && !isLoading && (
          <Alert variant='destructive' data-testid='upcoming-error'>
            <p>Failed to load upcoming activities: {error.message}</p>
          </Alert>
        )}

        {!isLoading && !error && (
          <div data-testid='upcoming-ready'>
            {entries.length === 0 ? (
              <p
                className='text-muted-foreground py-4 text-sm'
                data-testid='upcoming-empty-state'
              >
                No upcoming outdoor activities in the next 30 days.
              </p>
            ) : (
              <ul
                className='space-y-3'
                aria-label='Upcoming outdoor activities'
              >
                {entries.map(entry => (
                  <li
                    key={entry.journal_id}
                    className='space-y-2 rounded-lg border p-4'
                    data-testid={`upcoming-activity-item-${entry.journal_id}`}
                  >
                    <div className='space-y-1'>
                      <Link
                        href={`/journals/${entry.journal_id}` as Route}
                        className='font-medium underline-offset-4 hover:underline'
                      >
                        {entry.title}
                      </Link>
                      <p className='text-muted-foreground text-sm'>
                        {formatDateRange(
                          entry.event_date_range.start,
                          entry.event_date_range.end
                        )}
                      </p>
                    </div>
                    <JournalTypeBadges
                      types={displayTypes(entry)}
                      data-testid={`upcoming-type-badges-${entry.journal_id}`}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
