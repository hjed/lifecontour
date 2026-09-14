/**
 * Post-mutation cache invalidation that cannot lose a race with an in-flight
 * fetch.
 *
 * Every mutation success handler should invalidate through this helper rather
 * than calling `queryClient.invalidateQueries` directly.
 *
 * Why (see issue #1203): `invalidateQueries` defaults to `cancelRefetch: true`,
 * but React Query only cancels the running request when the query *already has
 * data*:
 *
 * ```ts
 * if (this.state.data !== undefined && fetchOptions?.cancelRefetch) {
 *   this.cancel({ silent: true })
 * } else if (this.#retryer) {
 *   return this.#retryer.promise   // reuses the pre-mutation request
 * }
 * ```
 *
 * A list loading for the first time — a fresh mount, or a new query key
 * produced by a filter change — therefore keeps the request that started before
 * the mutation. When it settles, React Query stores its pre-mutation rows,
 * clears `isInvalidated` and stamps a fresh `dataUpdatedAt`, so the app-wide
 * `staleTime` (5 minutes, see `lib/query-client-options.ts`) suppresses any further
 * refetch and the user keeps seeing data they just changed. Inactive queries
 * have the same shape: invalidated but not refetched, then un-invalidated by
 * the late response.
 *
 * `cancelQueries` has no such guard, so cancelling first closes the race.
 */

import type {
  InvalidateQueryFilters,
  QueryClient,
  QueryFilters,
} from '@tanstack/react-query';

/**
 * Narrows an invalidation filter to what `cancelQueries` accepts.
 *
 * `refetchType` is an invalidation-only concern, so it is dropped. When it says
 * `'none'` — mark the queries stale, do not go near the network — the filter is
 * additionally narrowed to queries that already hold data, because the two
 * halves of that request pull in opposite directions:
 *
 * - A query **with** data must be cancelled, or the in-flight response settles
 *   afterwards and clears `isInvalidated`, undoing the mark-stale the caller
 *   asked for. Cancelling reverts it to the data it was already showing, so
 *   there is nothing to re-fetch and nothing to re-render.
 * - A query **without** data must not be cancelled. Nothing has refetched it —
 *   `refetchType: 'none'` said not to — so an observer waiting on its first
 *   load would sit at `status: 'pending'`, `fetchStatus: 'idle'` indefinitely: a
 *   spinner that never resolves. Letting its request land is strictly better,
 *   even though the rows it brings are pre-mutation ones.
 */
function toQueryFilters(filters: InvalidateQueryFilters): QueryFilters {
  const { refetchType, ...queryFilters } = filters;

  if (refetchType !== 'none') {
    return queryFilters;
  }

  const { predicate } = queryFilters;
  return {
    ...queryFilters,
    predicate: query =>
      query.state.data !== undefined && (predicate?.(query) ?? true),
  };
}

/**
 * Cancels the fetches matching every filter, then invalidates them all.
 *
 * Pass all of a handler's key sets in one call: they must *all* be cancelled
 * before *any* of them is invalidated, otherwise the invalidation of the first
 * key set can trigger fetches that the later cancels then tear down — and the
 * later key sets stay exposed to the race this helper exists to close.
 *
 * A filter carrying `refetchType: 'none'` cancels only the queries that already
 * hold data — see `toQueryFilters` for why the first-load ones are left alone.
 *
 * Handlers may call this fire-and-forget, exactly as they called
 * `invalidateQueries`; the returned promise is there for tests and for handlers
 * that need to await the refetch.
 */
export async function invalidateAfterMutation(
  queryClient: QueryClient,
  ...filters: InvalidateQueryFilters[]
): Promise<void> {
  await Promise.all(
    filters.map(filter => queryClient.cancelQueries(toQueryFilters(filter)))
  );

  await Promise.all(
    filters.map(filter => queryClient.invalidateQueries(filter))
  );
}
