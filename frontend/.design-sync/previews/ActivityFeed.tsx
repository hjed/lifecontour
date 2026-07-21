import { ActivityFeed } from 'personal-management-frontend';
import type { UseHistoryHook } from 'personal-management-frontend';
import type { HistoryListResponse } from '@/types/history';

/**
 * The feed is parameterised by its data hook (see `UseHistoryHook`), so these
 * cards drive the real component with stub hooks — the same seam the
 * component's own tests use — instead of hitting the API.
 */
function stubHook(result: {
  data: HistoryListResponse | undefined;
  isLoading: boolean;
  error: Error | null;
  isFetching: boolean;
}): UseHistoryHook {
  return () => result;
}

const contactHistory: HistoryListResponse = {
  data: [
    {
      type: 'contact_history',
      id: '1',
      attributes: {
        entity_type: 'contact',
        entity_id: 318,
        field_name: 'favourite',
        old_value: 'false',
        new_value: 'true',
        changed_by: 'alex.taylor@example.com',
        source: 'ui',
        created_at: '2024-05-15T10:05:00Z',
      },
    },
    {
      type: 'contact_history',
      id: '2',
      attributes: {
        entity_type: 'contact',
        entity_id: 318,
        field_name: 'phone_number',
        old_value: null,
        new_value: '+61 412 555 019',
        changed_by: 'sync@example.com',
        source: 'google_contacts',
        created_at: '2024-05-14T22:40:00Z',
      },
    },
    {
      type: 'contact_history',
      id: '3',
      attributes: {
        entity_type: 'contact',
        entity_id: 318,
        field_name: 'last_name',
        old_value: 'Nair',
        new_value: 'Nair-Osei',
        changed_by: 'alex.taylor@example.com',
        source: 'mcp',
        created_at: '2024-05-13T01:20:00Z',
      },
    },
    {
      type: 'contact_history',
      id: '4',
      attributes: {
        entity_type: 'contact',
        entity_id: 318,
        field_name: 'company',
        old_value: 'Ridgeline Outdoors',
        new_value: null,
        changed_by: 'alex.taylor@example.com',
        source: 'ui',
        created_at: '2024-05-09T04:00:00Z',
      },
    },
  ],
  meta: { total_count: 24, page_count: 3, current_page: 1, per_page: 4 },
};

/** Populated contact timeline, paginated — the Load More affordance shows. */
export function ContactHistory() {
  return (
    <ActivityFeed
      entityId='318'
      pageSize={4}
      useHistory={stubHook({
        data: contactHistory,
        isLoading: false,
        error: null,
        isFetching: false,
      })}
    />
  );
}

/** Empty state; the copy is entity-aware. */
export function EmptyJournal() {
  return (
    <ActivityFeed
      entityId='912'
      entity='journal'
      useHistory={stubHook({
        data: { data: [], meta: undefined },
        isLoading: false,
        error: null,
        isFetching: false,
      })}
    />
  );
}

/** First load. */
export function Loading() {
  return (
    <ActivityFeed
      entityId='318'
      useHistory={stubHook({
        data: undefined,
        isLoading: true,
        error: null,
        isFetching: true,
      })}
    />
  );
}

/** The fetch failed — the feed surfaces the error message inline. */
export function LoadFailed() {
  return (
    <ActivityFeed
      entityId='318'
      useHistory={stubHook({
        data: undefined,
        isLoading: false,
        error: new Error('Request failed with status 503'),
        isFetching: false,
      })}
    />
  );
}
