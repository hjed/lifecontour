/**
 * ActivityFeed component displays a timeline of an entity's activity/history.
 *
 * Entity-agnostic: parameterised by a data hook so it can be reused across
 * contacts, journals, and any future history surface.
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
import { TooltipProvider } from '@/components/ui/tooltip';
import type {
  HistoryFilters,
  HistoryListResponse,
  HistoryResource,
} from '@/types/history';
import type { HistoryEntity } from '@/lib/history-display';
import { ActivityItem } from './ActivityItem';

/**
 * The entity whose history is being displayed.
 *
 * It drives the empty-state copy, and — since ITER18-003 Phase 9 — reaches
 * each entry, because a task's contact-membership row reads one way on the
 * task's own history and another on the person's. Re-exported from
 * `lib/history-display`, where the wording that depends on it lives, so the
 * two cannot list different entities.
 */
export type { HistoryEntity };

/**
 * Data hook contract the feed depends on. The shape is a structural subset of a
 * TanStack Query `UseQueryResult`, so entity-specific hooks (e.g.
 * `useContactHistory`) can be passed directly.
 */
export type UseHistoryHook = (
  entityId: string,
  filters?: HistoryFilters,
  options?: { enabled?: boolean }
) => {
  data: HistoryListResponse | undefined;
  isLoading: boolean;
  error: Error | null;
  isFetching: boolean;
};

interface ActivityFeedProps {
  readonly entityId: string;
  /** Data hook returning the entity's paginated history. */
  readonly useHistory: UseHistoryHook;
  /** Entity kind, used for empty-state copy (default: 'contact'). */
  readonly entity?: HistoryEntity;
  readonly className?: string;
  /** Initial page size (default: 10) */
  readonly pageSize?: number;
  /**
   * The card's heading, or `null` to render no header at all.
   *
   * `null` exists for the feed a journal's task row embeds. That page already
   * has an "Activity" heading of its own, and a journal holding five open task
   * rows would otherwise present six identically-named `h3`s nested inside a
   * list — indistinguishable to anyone navigating by heading, which is exactly
   * what the row's trigger label exists to prevent. A headerless feed is
   * labelled by the disclosure that opened it instead.
   */
  readonly title?: string | null;
}

const DEFAULT_PAGE_SIZE = 10;

function emptyStateDescription(entity: HistoryEntity): string {
  return `Changes to this ${entity} will appear here`;
}

// Reducer for managing activities state
type ActivitiesState = {
  activities: HistoryResource[];
  entityId: string;
  page: number;
  processedDataKey: string | null;
};

type ActivitiesAction =
  | { type: 'RESET'; entityId: string }
  | { type: 'SET_PAGE'; page: number }
  | {
      type: 'SET_ACTIVITIES';
      activities: HistoryResource[];
      dataKey: string;
    }
  | {
      type: 'APPEND_ACTIVITIES';
      activities: HistoryResource[];
      dataKey: string;
    };

function activitiesReducer(
  state: ActivitiesState,
  action: ActivitiesAction
): ActivitiesState {
  switch (action.type) {
    case 'RESET':
      if (state.entityId === action.entityId) return state;
      return {
        activities: [],
        entityId: action.entityId,
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
  entityId,
  useHistory,
  entity = 'contact',
  className,
  pageSize = DEFAULT_PAGE_SIZE,
  title = 'Activity',
}: ActivityFeedProps) {
  const [state, dispatch] = useReducer(activitiesReducer, {
    activities: [],
    entityId,
    page: 1,
    processedDataKey: null,
  });

  const { data, isLoading, error, isFetching } = useHistory(entityId, {
    page: state.page,
    limit: pageSize,
  });

  // Reset state when entityId changes
  useEffect(() => {
    dispatch({ type: 'RESET', entityId });
  }, [entityId]);

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
      {title !== null && (
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <Clock className='h-5 w-5' />
            {title}
          </CardTitle>
        </CardHeader>
      )}
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
            <p className='text-sm'>{emptyStateDescription(entity)}</p>
          </div>
        )}

        {/* Activity list */}
        {!isLoading && !error && state.activities.length > 0 && (
          <TooltipProvider>
            <div className='space-y-1'>
              {state.activities.map(activity => (
                <ActivityItem
                  key={activity.id}
                  activity={activity}
                  entity={entity}
                />
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
          </TooltipProvider>
        )}
      </CardContent>
    </Card>
  );
}
