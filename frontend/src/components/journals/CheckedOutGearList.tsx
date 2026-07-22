/**
 * CheckedOutGearList — the dashboard's currently checked-out gear.
 *
 * Lists the gear items the user has out right now, longest-out first (the
 * backend's ordering), each with the date it went out. "Checked out" means the
 * resolved checkout window contains now and no successful SnipeIT check-in has
 * been recorded (see database-design.md); the rows are informational text —
 * there is no per-gear-item page to link to.
 */

'use client';

import { Package } from 'lucide-react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { WidgetEmptyState } from '@/components/journals/WidgetEmptyState';
import { useOutdoorDashboard } from '@/lib/api/outdoor-dashboard';
import { formatDateRange } from '@/lib/date-utils';

export function CheckedOutGearList() {
  const { data, isLoading, error } = useOutdoorDashboard();

  const items = data?.data.attributes.checked_out_gear ?? [];

  return (
    <Card className='flex flex-col'>
      <CardHeader>
        <CardTitle>Gear currently checked out</CardTitle>
        <CardDescription>
          Gear you have out right now, longest out first.
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-1 flex-col'>
        {isLoading && (
          <div className='space-y-3' data-testid='checked-out-gear-loading'>
            <Skeleton className='h-12 w-full' />
            <Skeleton className='h-12 w-full' />
          </div>
        )}

        {error && !isLoading && (
          <Alert variant='destructive' data-testid='checked-out-gear-error'>
            <p>Failed to load checked-out gear: {error.message}</p>
          </Alert>
        )}

        {!isLoading && !error && (
          <div
            className='flex flex-1 flex-col'
            data-testid='checked-out-gear-ready'
          >
            {items.length === 0 ? (
              <WidgetEmptyState
                icon={Package}
                message='No gear is currently checked out.'
                data-testid='checked-out-gear-empty-state'
              />
            ) : (
              <ul className='space-y-3' aria-label='Gear currently checked out'>
                {items.map(item => (
                  <li
                    key={item.gear_item_id}
                    className='flex items-center gap-3 rounded-lg border p-4'
                    data-testid={`checked-out-gear-item-${item.gear_item_id}`}
                  >
                    <Package
                      className='text-muted-foreground h-4 w-4 shrink-0'
                      aria-hidden='true'
                    />
                    <div className='min-w-0 space-y-1'>
                      <p className='text-foreground font-medium'>{item.name}</p>
                      <p className='text-muted-foreground text-sm'>
                        Checked out since{' '}
                        {formatDateRange(
                          item.checked_out_since,
                          item.checked_out_since
                        )}
                      </p>
                    </div>
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
