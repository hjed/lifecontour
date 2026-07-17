/**
 * ActivityTotalsTable — the dashboard's recent activity totals.
 *
 * Counts of the user's outdoor activities by journal type over two rolling
 * windows shown together: the last 30 days and the last 365 days. Types are
 * the effective (dependency-reduced) journal types computed server-side.
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
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableRowHeader,
} from '@/components/ui/table';
import {
  TYPE_ICONS,
  TYPE_LABELS,
} from '@/components/journals/JournalTypeBadges';
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

export function ActivityTotalsTable() {
  const { data, isLoading, error } = useOutdoorDashboard();

  const totals = data?.data.attributes.activity_totals ?? {
    last_30_days: {},
    last_365_days: {},
  };
  const types = totalTypes(totals);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent activity totals</CardTitle>
        <CardDescription>
          Outdoor activities by type over the rolling last 30 days and last 365
          days.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className='space-y-3' data-testid='totals-loading'>
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
          <div data-testid='totals-ready'>
            {types.length === 0 ? (
              <p
                className='text-muted-foreground py-4 text-sm'
                data-testid='totals-empty-state'
              >
                No outdoor activity recorded in the last year.
              </p>
            ) : (
              <Table data-testid='activity-totals-table'>
                <TableCaption className='sr-only'>
                  Outdoor activity counts by type over the last 30 and 365 days
                </TableCaption>
                <TableHeader>
                  <TableRow>
                    <TableHead>Activity</TableHead>
                    <TableHead className='text-right'>Last 30 days</TableHead>
                    <TableHead className='text-right'>Last 365 days</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {types.map(type => {
                    const Icon = TYPE_ICONS[type];
                    return (
                      <TableRow key={type} data-testid={`totals-row-${type}`}>
                        <TableRowHeader>
                          <span className='flex items-center gap-1.5'>
                            {Icon && (
                              <Icon
                                className='h-3.5 w-3.5'
                                aria-hidden='true'
                              />
                            )}
                            <span>{TYPE_LABELS[type] ?? type}</span>
                          </span>
                        </TableRowHeader>
                        <TableCell
                          className='text-right'
                          data-testid={`totals-30d-${type}`}
                        >
                          {totals.last_30_days[type] ?? 0}
                        </TableCell>
                        <TableCell
                          className='text-right'
                          data-testid={`totals-365d-${type}`}
                        >
                          {totals.last_365_days[type] ?? 0}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
