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

import { useCallback, useReducer, useEffect } from 'react';
import { Clock, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useContactHistory } from '@/lib/api/contacts';
import { ActivityItem } from './ActivityItem';
import type { ContactHistoryResource } from '@/types/contacts';

interface ActivityFeedProps {
  readonly contactId: string;
  readonly className?: string;
  /** Initial page size (default: 10) */
  readonly pageSize?: number;
}

const DEFAULT_PAGE_SIZE = 10;

// Reducer for managing activities state
type ActivitiesState = {
  activities: ContactHistoryResource[];
  contactId: string;
  page: number;
  processedDataKey: string | null;
};

type ActivitiesAction =
  | { type: 'RESET'; contactId: string }
  | { type: 'SET_PAGE'; page: number }
  | {
      type: 'SET_ACTIVITIES';
      activities: ContactHistoryResource[];
      dataKey: string;
    }
  | {
      type: 'APPEND_ACTIVITIES';
      activities: ContactHistoryResource[];
      dataKey: string;
    };

function activitiesReducer(
  state: ActivitiesState,
  action: ActivitiesAction
): ActivitiesState {
  switch (action.type) {
    case 'RESET':
      if (state.contactId === action.contactId) return state;
      return {
        activities: [],
        contactId: action.contactId,
        page: 1,
        processedDataKey: null,
      };
    case 'SET_PAGE':
      return { ...state, page: action.page };
    case 'SET_ACTIVITIES':
      if (state.processedDataKey === action.dataKey) return state;
      return {
        ...state,
        activities: action.activities,
        processedDataKey: action.dataKey,
      };
    case 'APPEND_ACTIVITIES': {
      if (state.processedDataKey === action.dataKey) return state;
      const existingIds = new Set(state.activities.map(a => a.id));
      const newActivities = action.activities.filter(
        a => !existingIds.has(a.id)
      );
      if (newActivities.length === 0)
        return { ...state, processedDataKey: action.dataKey };
      return {
        ...state,
        activities: [...state.activities, ...newActivities],
        processedDataKey: action.dataKey,
      };
    }
    default:
      return state;
  }
}

export function ActivityFeed({
  contactId,
  className,
  pageSize = DEFAULT_PAGE_SIZE,
}: ActivityFeedProps) {
  const [state, dispatch] = useReducer(activitiesReducer, {
    activities: [],
    contactId,
    page: 1,
    processedDataKey: null,
  });

  const { data, isLoading, error, isFetching } = useContactHistory(contactId, {
    page: state.page,
    limit: pageSize,
  });

  // Reset state when contactId changes
  useEffect(() => {
    dispatch({ type: 'RESET', contactId });
  }, [contactId]);

  // Update activities when data changes
  useEffect(() => {
    if (!data) return;

    const currentDataKey = `${state.page}-${data.data.map(a => a.id).join(',')}`;

    if (state.page === 1) {
      dispatch({
        type: 'SET_ACTIVITIES',
        activities: data.data,
        dataKey: currentDataKey,
      });
    } else {
      dispatch({
        type: 'APPEND_ACTIVITIES',
        activities: data.data,
        dataKey: currentDataKey,
      });
    }
  }, [data, state.page]);

  const hasMore =
    data?.meta?.current_page !== undefined &&
    data?.meta?.page_count !== undefined &&
    data.meta.current_page < data.meta.page_count;

  const handleLoadMore = useCallback(() => {
    dispatch({ type: 'SET_PAGE', page: state.page + 1 });
  }, [state.page]);

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
        {!isLoading && !error && state.activities.length === 0 && (
          <div className='text-muted-foreground py-8 text-center'>
            <Clock className='mx-auto mb-4 h-12 w-12 opacity-50' />
            <p className='text-lg font-medium'>No activity yet</p>
            <p className='text-sm'>Changes to this contact will appear here</p>
          </div>
        )}

        {/* Activity list */}
        {!isLoading && !error && state.activities.length > 0 && (
          <div className='space-y-1'>
            {state.activities.map(activity => (
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
