/**
 * @jest-environment jsdom
 */

/**
 * Regression tests for the post-mutation invalidation race (#1203).
 *
 * A list fetch that starts *before* a mutation but settles *after* its
 * invalidation used to overwrite the cache with pre-mutation rows and mark them
 * fresh, so `staleTime` suppressed any further refetch and the list kept showing
 * data the user had already deleted.
 */

import { QueryClient, QueryObserver } from '@tanstack/react-query';
import { waitFor } from '@testing-library/react';
import { invalidateAfterMutation } from '../invalidate-after-mutation';

const LIST_KEY = ['journals', 'list'] as const;
const TAGS_KEY = ['journals', 'tags', 'list'] as const;

const PRE_MUTATION_ROWS = ['journal-with-deleted-tag'];
const POST_MUTATION_ROWS = ['journal-without-deleted-tag'];

const STALE_TIME_MS = 5 * 60 * 1000;

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(res => {
    resolve = res;
  });
  return { promise, resolve };
}

function createClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: STALE_TIME_MS, gcTime: Infinity },
    },
  });
}

/**
 * Query function whose first call hangs on `inFlight` (the pre-mutation fetch)
 * and whose later calls resolve immediately with the post-mutation rows.
 */
function createQueryFn(inFlight: Deferred<string[]>) {
  return jest
    .fn<Promise<string[]>, []>()
    .mockImplementationOnce(() => inFlight.promise)
    .mockImplementation(() => Promise.resolve(POST_MUTATION_ROWS));
}

/** Subscribes an observer and waits until its first fetch is in flight. */
async function startInFlightFetch(
  queryClient: QueryClient,
  queryFn: () => Promise<string[]>
): Promise<() => void> {
  const observer = new QueryObserver(queryClient, {
    queryKey: [...LIST_KEY],
    queryFn,
  });
  const unsubscribe = observer.subscribe(() => {});
  await waitFor(() =>
    expect(queryClient.getQueryState([...LIST_KEY])?.fetchStatus).toBe(
      'fetching'
    )
  );
  return unsubscribe;
}

describe('post-mutation invalidation race (#1203)', () => {
  describe('plain invalidateQueries (characterises the bug)', () => {
    it('lets a fetch that started before the invalidation settle over the cache and mark it fresh', async () => {
      const queryClient = createClient();
      const inFlight = deferred<string[]>();
      const queryFn = createQueryFn(inFlight);
      const unsubscribe = await startInFlightFetch(queryClient, queryFn);

      // The mutation succeeded and invalidated the list, exactly as a handler
      // does today — fire and forget.
      void queryClient.invalidateQueries({ queryKey: [...LIST_KEY] });

      // The pre-mutation request now comes back.
      inFlight.resolve(PRE_MUTATION_ROWS);
      await waitFor(() =>
        expect(queryClient.getQueryData([...LIST_KEY])).toEqual(
          PRE_MUTATION_ROWS
        )
      );

      // React Query reuses an in-flight fetch when the query has no data yet,
      // so nothing refetched and the stale rows are now considered fresh.
      expect(queryFn).toHaveBeenCalledTimes(1);
      expect(queryClient.getQueryState([...LIST_KEY])?.isInvalidated).toBe(
        false
      );

      unsubscribe();
      queryClient.clear();
    });
  });

  describe('invalidateAfterMutation', () => {
    it('discards a fetch that started before the mutation and refetches instead', async () => {
      const queryClient = createClient();
      const inFlight = deferred<string[]>();
      const queryFn = createQueryFn(inFlight);
      const unsubscribe = await startInFlightFetch(queryClient, queryFn);

      await invalidateAfterMutation(queryClient, { queryKey: [...LIST_KEY] });

      // The pre-mutation request settles late; its rows must never be cached.
      inFlight.resolve(PRE_MUTATION_ROWS);
      await Promise.resolve();

      await waitFor(() =>
        expect(queryClient.getQueryData([...LIST_KEY])).toEqual(
          POST_MUTATION_ROWS
        )
      );
      expect(queryFn).toHaveBeenCalledTimes(2);
      expect(queryClient.getQueryData([...LIST_KEY])).not.toEqual(
        PRE_MUTATION_ROWS
      );

      unsubscribe();
      queryClient.clear();
    });

    it('leaves an inactive query invalidated rather than freshly stale', async () => {
      const queryClient = createClient();
      const inFlight = deferred<string[]>();
      const queryFn = createQueryFn(inFlight);

      // No observer: the query is inactive, so invalidation marks it without
      // refetching and a late response would otherwise clear the invalid flag.
      const fetch = queryClient
        .fetchQuery({ queryKey: [...LIST_KEY], queryFn })
        .catch(() => undefined);
      await waitFor(() =>
        expect(queryClient.getQueryState([...LIST_KEY])?.fetchStatus).toBe(
          'fetching'
        )
      );

      await invalidateAfterMutation(queryClient, { queryKey: [...LIST_KEY] });

      inFlight.resolve(PRE_MUTATION_ROWS);
      await fetch;
      await Promise.resolve();

      expect(queryClient.getQueryData([...LIST_KEY])).toBeUndefined();
      expect(queryClient.getQueryState([...LIST_KEY])?.isInvalidated).toBe(
        true
      );
      expect(queryFn).toHaveBeenCalledTimes(1);

      queryClient.clear();
    });

    it('cancels every key set before invalidating any of them', async () => {
      const queryClient = createClient();
      const calls: string[] = [];

      jest
        .spyOn(queryClient, 'cancelQueries')
        .mockImplementation(async filters => {
          calls.push(`cancel:${JSON.stringify(filters?.queryKey)}`);
        });
      jest
        .spyOn(queryClient, 'invalidateQueries')
        .mockImplementation(async filters => {
          calls.push(`invalidate:${JSON.stringify(filters?.queryKey)}`);
        });

      await invalidateAfterMutation(
        queryClient,
        { queryKey: [...TAGS_KEY] },
        { queryKey: [...LIST_KEY] }
      );

      expect(calls).toEqual([
        `cancel:${JSON.stringify(TAGS_KEY)}`,
        `cancel:${JSON.stringify(LIST_KEY)}`,
        `invalidate:${JSON.stringify(TAGS_KEY)}`,
        `invalidate:${JSON.stringify(LIST_KEY)}`,
      ]);

      jest.restoreAllMocks();
      queryClient.clear();
    });

    describe("with refetchType: 'none'", () => {
      it('still cancels a query that already has data, so the mark-stale sticks', async () => {
        const queryClient = createClient();
        const inFlight = deferred<string[]>();
        const queryFn = createQueryFn(inFlight);

        // Seed the data a mark-stale request is about, then start the refetch
        // that the mutation is racing. The seeded data is fresh, so the
        // refetch has to be asked for rather than arriving with the observer.
        queryClient.setQueryData([...LIST_KEY], ['already-rendered']);
        const observer = new QueryObserver(queryClient, {
          queryKey: [...LIST_KEY],
          queryFn,
        });
        const unsubscribe = observer.subscribe(() => {});
        void observer.refetch();
        await waitFor(() =>
          expect(queryClient.getQueryState([...LIST_KEY])?.fetchStatus).toBe(
            'fetching'
          )
        );

        await invalidateAfterMutation(queryClient, {
          queryKey: [...LIST_KEY],
          refetchType: 'none',
        });

        inFlight.resolve(PRE_MUTATION_ROWS);
        await Promise.resolve();

        // Cancelling reverted it to the rows it was already showing, and the
        // late response cannot clear the invalidation the caller asked for.
        expect(queryClient.getQueryData([...LIST_KEY])).toEqual([
          'already-rendered',
        ]);
        expect(queryClient.getQueryState([...LIST_KEY])?.isInvalidated).toBe(
          true
        );

        unsubscribe();
        queryClient.clear();
      });

      it('leaves a first-load query fetching rather than stranding it on a spinner', async () => {
        const queryClient = createClient();
        const inFlight = deferred<string[]>();
        const queryFn = createQueryFn(inFlight);
        const unsubscribe = await startInFlightFetch(queryClient, queryFn);

        await invalidateAfterMutation(queryClient, {
          queryKey: [...LIST_KEY],
          refetchType: 'none',
        });

        // Nothing will refetch it — that is what 'none' means — so cancelling
        // would leave it pending for ever. Its response must still land.
        inFlight.resolve(PRE_MUTATION_ROWS);
        await waitFor(() =>
          expect(queryClient.getQueryData([...LIST_KEY])).toEqual(
            PRE_MUTATION_ROWS
          )
        );
        expect(queryFn).toHaveBeenCalledTimes(1);

        unsubscribe();
        queryClient.clear();
      });
    });
  });
});
