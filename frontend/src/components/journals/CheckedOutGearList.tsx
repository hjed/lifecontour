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
import { useOutdoorDashboard } from '@/lib/api/outdoor-dashboard';
import { formatDateRange } from '@/lib/date-utils';

export function CheckedOutGearList() {
  const { data, isLoading, error } = useOutdoorDashboard();

  const items = data?.data.attributes.checked_out_gear ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Gear currently checked out</CardTitle>
        <CardDescription>
          Gear you have out right now, longest out first.
        </CardDescription>
      </CardHeader>
      <CardContent>
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
          <div data-testid='checked-out-gear-ready'>
            {items.length === 0 ? (
              <p
                className='text-muted-foreground py-4 text-sm'
                data-testid='checked-out-gear-empty-state'
              >
                No gear is currently checked out.
              </p>
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
