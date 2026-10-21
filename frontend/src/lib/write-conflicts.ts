/**
 * Writes the server refused because their aggregate moved on (`412`).
 *
 * One global handler, wired into the `MutationCache` by `createAppQueryClient`,
 * turns every refused aggregate write into an entry here: it re-reads the
 * aggregate, works out what changed, and keeps a way to re-apply the write.
 * `WriteConflictDialog` renders the entries. Hooks therefore never handle a 412
 * themselves — they only skip their own error toast for one
 * (`isWriteConflict`).
 */

import type { Mutation, QueryClient } from '@tanstack/react-query';
import { useSyncExternalStore } from 'react';
import {
  diffAggregate,
  type AggregateDocument,
} from '@/lib/api/aggregate-diff';
import type { AggregateKind } from '@/lib/api/aggregate-write';
import { PreconditionFailedError } from '@/lib/api/conditional-request';
import type { Versioned } from '@/lib/api/versioned-cache';

export interface WriteConflict {
  id: number;
  kind: AggregateKind;
  /**
   * Whether the aggregate was re-read. Until it is, the page still shows the
   * version the write was refused against, so neither choice is offered.
   */
  refreshed: boolean;
  /** Labels of the parts of the aggregate that changed; empty if none shown. */
  changed: string[];
  /** The refused change in words, when the write could describe itself. */
  attempted?: string;
  /**
   * Sends the refused write again, against the version just re-read. Settles
   * the conflict when the write lands or is refused again (which opens a new
   * one); rejects, leaving it open, when the write fails for another reason.
   */
  reapply: () => Promise<void>;
  /** Tries the failed re-read again. */
  retryRefresh: () => Promise<void>;
}

/** The parts of each aggregate a user edits, and what to call them. */
export const AGGREGATE_LABELS: Record<AggregateKind, Record<string, string>> = {
  contact: {
    first_name: 'First name',
    middle_name: 'Middle name',
    last_name: 'Last name',
    nick_name: 'Nickname',
    is_favourite: 'Favourite',
    contact_methods: 'Contact methods',
    addresses: 'Addresses',
    notes: 'Notes',
    important_dates: 'Important dates',
    tags: 'Tags',
  },
  journal: {
    title: 'Title',
    content: 'Content',
    event_date_range: 'Date',
    types: 'Types',
    type_data: 'Type details',
    contacts: 'People',
    tags: 'Tags',
  },
};

let conflicts: readonly WriteConflict[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function publish(next: readonly WriteConflict[]): void {
  conflicts = next;
  listeners.forEach(listener => listener());
}

export function getWriteConflicts(): readonly WriteConflict[] {
  return conflicts;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The open conflicts, oldest first. */
export function useWriteConflicts(): readonly WriteConflict[] {
  return useSyncExternalStore(subscribe, getWriteConflicts, getWriteConflicts);
}

/** Updates a conflict still open, e.g. after its re-read was retried. */
function replaceWriteConflict(next: WriteConflict): void {
  publish(
    conflicts.map(conflict => (conflict.id === next.id ? next : conflict))
  );
}

export function dismissWriteConflict(id: number): void {
  publish(conflicts.filter(conflict => conflict.id !== id));
}

/** Clears every conflict. For tests. */
export function resetWriteConflicts(): void {
  publish([]);
}

/** Whether a failed write is a conflict the dialog will report. */
export function isWriteConflict(error: unknown): boolean {
  return error instanceof PreconditionFailedError;
}

/**
 * The `MutationCache.onError` half of conflict handling.
 *
 * It runs for every failed mutation, so it acts only on a 412 from a write
 * that declared its aggregate in `meta.conflict` (see `aggregateWrite`).
 * Awaiting the re-read matters: the mutation's scope does not move on until
 * this settles, so a write queued behind the refused one is sent with the
 * refreshed tag rather than refused for the same reason.
 */
export async function handleWriteConflict(
  queryClient: QueryClient,
  error: unknown,
  variables: unknown,
  mutation: Mutation<unknown, unknown, unknown, unknown>
): Promise<void> {
  const conflict = mutation.meta?.conflict;
  if (!isWriteConflict(error) || !conflict) return;

  const queryCache = queryClient.getQueryCache();
  const version = () =>
    queryClient.getQueryData<Versioned<AggregateDocument>>(conflict.detailKey);
  const before = version()?.resource;
  const id = nextId++;
  // The detail query's options carry the function that reads it. A dialog can
  // outlive the page (and the detail's gcTime); what is kept here lets it put
  // the detail back, readable, rather than reading or replaying without it.
  const detailOptions = queryCache.find({
    queryKey: conflict.detailKey,
    exact: true,
  })?.options;
  /** The version the dialog last stood on: refused against, then re-read. */
  let known = version();

  /**
   * Puts the version the dialog last saw back into a detail that has lost it:
   * evicted, or evicted and being read again by a revisited page. Without it a
   * replay would read no tag and send no `If-Match`, and a re-read would find
   * nothing to refetch. Cancel any read of the detail first, or cancelling it
   * later reverts this.
   */
  const restoreDetail = (): void => {
    if (!detailOptions || !known) return;
    if (queryClient.getQueryData(conflict.detailKey) !== undefined) return;
    queryCache.build(queryClient, {
      ...detailOptions,
      queryKey: conflict.detailKey,
    });
    queryClient.setQueryData(conflict.detailKey, known);
  };

  /** Re-reads the aggregate; false when the read failed or never ran. */
  const refresh = async (): Promise<boolean> => {
    // A first read still in flight may have left before the change that
    // refused the write, and refetching would join it rather than restart it.
    await queryClient.cancelQueries({ queryKey: conflict.detailKey });
    restoreDetail();
    const updatesBefore =
      queryClient.getQueryState(conflict.detailKey)?.dataUpdateCount ?? 0;
    try {
      // `refetchQueries`, not `fetchQuery`: it reuses the query function the
      // detail query registered, where `fetchQuery` would need it restated.
      // Without `throwOnError` a failed read would pass for a fresh one.
      // Not `exact`: reads nested under the detail key (a contact's tags) are
      // part of what the page shows of the record, and the dialog is about to
      // say the page shows the latest version of it.
      await queryClient.refetchQueries(
        { queryKey: conflict.detailKey },
        { throwOnError: true }
      );
    } catch {
      return false;
    }
    // `refetchQueries` resolves at once for a query paused offline: only a
    // read that actually landed counts as fresh.
    const state = queryClient.getQueryState(conflict.detailKey);
    const fresh =
      state !== undefined &&
      state.fetchStatus !== 'paused' &&
      state.dataUpdateCount > updatesBefore;
    if (fresh) known = version();
    return fresh;
  };

  const settled = (refreshed: boolean): WriteConflict => ({
    id,
    kind: conflict.kind,
    refreshed,
    // Without the fresh copy there is nothing to compare against.
    changed: refreshed
      ? diffAggregate(
          before,
          version()?.resource,
          AGGREGATE_LABELS[conflict.kind]
        )
      : [],
    attempted: conflict.describe?.(variables),
    retryRefresh: async () => replaceWriteConflict(settled(await refresh())),
    reapply: async () => {
      await queryClient.cancelQueries({
        queryKey: conflict.detailKey,
        exact: true,
      });
      restoreDetail();
      try {
        // The same options — scope, callbacks, meta — so the retry queues
        // behind any other write to the aggregate and reads the fresh tag.
        await queryClient
          .getMutationCache()
          .build(queryClient, mutation.options)
          .execute(variables);
      } catch (retryError) {
        // Refused again: this handler has already opened its successor.
        // Anything else keeps this conflict, so the change is not lost.
        if (!isWriteConflict(retryError)) throw retryError;
      }
      dismissWriteConflict(id);
    },
  });

  // Read `conflicts` only after the re-read: another conflict may have been
  // added, or one dismissed, while it was in flight.
  const refreshed = await refresh();
  publish([...conflicts, settled(refreshed)]);
}
