/**
 * What every write to a contact or journal aggregate shares.
 *
 * The aggregate's `ETag` covers the root row and every row it renders, so the
 * writes to one aggregate form a single version history. Two inline edits sent
 * in parallel would each carry the same tag and the second would be refused for
 * the first one's change. TanStack Query's mutation `scope` runs mutations that
 * share a scope id one after another, so each write reads — at the moment its
 * turn comes, not when it was queued — the tag the previous one stored.
 *
 * See `docs/architecture/api-design.md` → Conditional Writes → Web client.
 */

import type { QueryClient, QueryKey } from '@tanstack/react-query';
import { ApiError, type ConditionalResult } from './conditional-request';
import { readEtag, storeEtag, updateResource } from './versioned-cache';

export type AggregateKind = 'contact' | 'journal';

/** One aggregate, and the detail query that holds its tag. */
export interface AggregateRef {
  kind: AggregateKind;
  id: string;
  detailKey: QueryKey;
}

/** What the global 412 handler needs to know about a refused write. */
export interface WriteConflictMeta extends AggregateRef {
  /** The attempted change in words, for the conflict dialog. */
  describe?: (variables: unknown) => string | undefined;
}

export interface AppMutationMeta extends Record<string, unknown> {
  conflict?: WriteConflictMeta;
}

declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: AppMutationMeta;
  }
}

/** The mutation key every aggregate write carries. */
export const AGGREGATE_WRITE_KEY = 'aggregate-write';

export function aggregateScopeId(kind: AggregateKind, id: string): string {
  return `${kind}:${id}`;
}

/**
 * Never retry a refusal; retry a server or network failure once.
 *
 * A refused write is refused again: a 412 resent with the same tag cannot
 * succeed, and a 4xx says the request itself is wrong. The app-wide default
 * (`retry: 1`) would resend both.
 */
function retryUnlessRefused(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < 1;
}

/**
 * Options to spread into every `useMutation` that writes to one aggregate.
 *
 * `describe` turns the mutation's variables into the attempted change the
 * conflict dialog shows, e.g. "Nickname → Bob".
 */
export function aggregateWrite<TVariables>(
  ref: AggregateRef,
  describe?: (variables: TVariables) => string | undefined
) {
  return {
    scope: { id: aggregateScopeId(ref.kind, ref.id) },
    mutationKey: [AGGREGATE_WRITE_KEY, ref.kind, ref.id],
    retry: retryUnlessRefused,
    meta: {
      conflict: {
        ...ref,
        // The meta registry is shared by every mutation, so it cannot name
        // this one's variables; the scope guarantees these are the ones the
        // handler is given.
        describe: describe
          ? (variables: unknown) => describe(variables as TVariables)
          : undefined,
      },
    },
  };
}

/**
 * Sends one guarded write and records the version it committed.
 *
 * Call from inside `mutationFn`, so the tag is read when the scope reaches
 * this mutation. Refetches of the detail are cancelled before the write and
 * again after it: any of them may have read the version before this write,
 * and landing after its tag is stored would put the older tag back.
 */
export interface GuardedWriteOptions {
  /**
   * The write answers with the whole aggregate, re-read after its commit.
   * Its body is stored with its tag: the re-read may include another tab's
   * change, and keeping only the tag would pair that version with the older
   * body — so the next edit would overwrite the change unrefused.
   */
  bodyIsResource?: boolean;
}

export async function sendGuarded<T>(
  queryClient: QueryClient,
  detailKey: QueryKey,
  send: (ifMatch: string | null) => Promise<ConditionalResult<T>>,
  { bodyIsResource = false }: GuardedWriteOptions = {}
): Promise<T> {
  await queryClient.cancelQueries({ queryKey: detailKey, exact: true });
  const { body, etag } = await send(readEtag(queryClient, detailKey));
  // And again once it has landed: a read started while the write was in
  // flight (a window refocus, say) may have read the version before it, and
  // arriving after the new tag is stored it would put the old one back.
  await queryClient.cancelQueries({ queryKey: detailKey, exact: true });
  if (bodyIsResource) {
    updateResource<T>(queryClient, detailKey, () => body);
  }
  storeEtag(queryClient, detailKey, etag);
  return body;
}

/**
 * `aggregateWrite`'s options plus the `mutationFn` that sends the write
 * guarded: everything a hook writing to one aggregate needs but its
 * callbacks.
 */
export function guardedWrite<TVariables, TBody>(
  queryClient: QueryClient,
  ref: AggregateRef,
  send: (
    variables: TVariables,
    ifMatch: string | null
  ) => Promise<ConditionalResult<TBody>>,
  describe?: (variables: TVariables) => string | undefined,
  options?: GuardedWriteOptions
) {
  return {
    ...aggregateWrite<TVariables>(ref, describe),
    mutationFn: (variables: TVariables) =>
      sendGuarded(
        queryClient,
        ref.detailKey,
        ifMatch => send(variables, ifMatch),
        options
      ),
  };
}
