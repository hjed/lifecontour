/**
 * ActivityFeed component displays a timeline of contact activity/history.
 *
 * Features:
 * - Timeline display of field changes
 * - Load More pagination
 * - Loading and empty states
 * - Error handling
 */

'use client';

import { useState } from 'react';
import { Clock, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useContactHistory } from '@/lib/api/contacts';
import { ActivityItem } from './ActivityItem';

interface ActivityFeedProps {
  readonly contactId: string;
  readonly className?: string;
  /** Initial page size (default: 10) */
  readonly pageSize?: number;
}

const DEFAULT_PAGE_SIZE = 10;

export function ActivityFeed({
  contactId,
  className,
  pageSize = DEFAULT_PAGE_SIZE,
}: ActivityFeedProps) {
  const [page, setPage] = useState(1);

  const { data, isLoading, error, isFetching } = useContactHistory(contactId, {
    page,
    limit: pageSize,
  });

  const activities = data?.data ?? [];
  const hasMore =
    data?.meta?.current_page !== undefined &&
    data?.meta?.page_count !== undefined &&
    data.meta.current_page < data.meta.page_count;

  const handleLoadMore = () => {
    setPage(prev => prev + 1);
  };

  return (
    <Card className={className} data-testid='activity-feed'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2'>
          <Clock className='h-5 w-5' />
          Activity
        </CardTitle>
      </CardHeader>
      <CardContent>
        {/* Loading state */}
        {isLoading && (
          <div className='flex items-center justify-center py-8'>
            <Loader2 className='h-6 w-6 animate-spin' />
            <span className='ml-2'>Loading activity...</span>
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className='text-destructive py-4 text-center'>
            <p>Error loading activity</p>
            <p className='text-sm'>{error.message}</p>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && activities.length === 0 && (
          <div className='text-muted-foreground py-8 text-center'>
            <Clock className='mx-auto mb-4 h-12 w-12 opacity-50' />
            <p className='text-lg font-medium'>No activity yet</p>
            <p className='text-sm'>Changes to this contact will appear here</p>
          </div>
        )}

        {/* Activity list */}
        {!isLoading && !error && activities.length > 0 && (
          <div className='space-y-1'>
            {activities.map(activity => (
              <ActivityItem key={activity.id} activity={activity} />
            ))}

            {/* Load More button */}
            {hasMore && (
              <div className='pt-4 text-center'>
                <Button
                  variant='outline'
                  size='sm'
                  onClick={handleLoadMore}
                  disabled={isFetching}
                >
                  {isFetching ? (
                    <>
                      <Loader2 className='mr-2 h-4 w-4 animate-spin' />
                      Loading...
                    </>
                  ) : (
                    'Load More'
                  )}
                </Button>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
