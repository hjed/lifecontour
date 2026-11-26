/**
 * Which of several overlapping optimistic moves is the newest, per scope.
 *
 * A drag applies its move to the cache at once, so two quick drags leave two
 * requests out, each holding a snapshot of an order the server may never
 * have had. Only the move that settles **last** knows the server has answered
 * everything, and only if it is also the **newest** is its answer the whole
 * truth; any other outcome is settled by re-reading. These helpers let a hook
 * tell the two apart, and remember whether any of the moves cancelled a
 * refresh that was already in flight — a refresh the re-sort alone would not
 * bring back.
 *
 * A scope is one thing overlapping writes can race on: the active listing's
 * order, one list's open-task order, or one list's own attributes (a rename
 * and an archive answered out of order).
 */

import type { QueryClient } from '@tanstack/react-query';

interface MoveScope {
  /** The ticket of the newest move started in this scope. */
  newest: number;
  /** Moves started and not yet settled. */
  pending: number;
  /** Whether a move cancelled a refresh in flight that nothing has redone. */
  interruptedRefresh: boolean;
  /**
   * Whether two moves were out at once since the scope was last settled. The
   * server may have applied them in either order, whatever order their
   * answers arrived in, so no answer alone can be trusted to be the final
   * order.
   */
  overlapped: boolean;
}

const scopesByClient = new WeakMap<QueryClient, Map<string, MoveScope>>();
let lastTicket = 0;

function scopeFor(queryClient: QueryClient, scope: string): MoveScope {
  let scopes = scopesByClient.get(queryClient);
  if (!scopes) {
    scopes = new Map();
    scopesByClient.set(queryClient, scopes);
  }

  let entry = scopes.get(scope);
  if (!entry) {
    entry = {
      newest: 0,
      pending: 0,
      interruptedRefresh: false,
      overlapped: false,
    };
    scopes.set(scope, entry);
  }
  return entry;
}

/**
 * Records a move starting, and whether it is about to cancel a refresh in
 * flight. Returns its ticket.
 */
export function startMove(
  queryClient: QueryClient,
  scope: string,
  interruptsRefresh: boolean
): number {
  const entry = scopeFor(queryClient, scope);
  lastTicket += 1;
  entry.newest = lastTicket;
  entry.overlapped ||= entry.pending > 0;
  entry.pending += 1;
  entry.interruptedRefresh ||= interruptsRefresh;
  return lastTicket;
}

/**
 * Records a move settling, and answers whether it was the last one pending.
 *
 * Counted here rather than read from `isMutating`: two requests answered in
 * the same tick each run their callbacks while the other is still marked
 * pending, so both would see "someone else is still out" and neither would
 * settle the order. A count decremented synchronously cannot be fooled that
 * way, and it is per scope, so a move in one list never waits on another.
 */
export function settleMove(queryClient: QueryClient, scope: string): boolean {
  const entry = scopeFor(queryClient, scope);
  entry.pending = Math.max(0, entry.pending - 1);
  return entry.pending === 0;
}

/** Whether no move has started in this scope since the one holding `ticket`. */
export function isNewestMove(
  queryClient: QueryClient,
  scope: string,
  ticket: number
): boolean {
  return scopeFor(queryClient, scope).newest === ticket;
}

/**
 * Whether the order must be confirmed by a re-read, rather than trusted to
 * the answer: a move cut short a refresh already in flight, or moves
 * overlapped (the server may have applied them in either order, whatever
 * order their answers arrived in). Asked by the last move to settle; asking
 * clears **both** reasons, so the next lone move starts clean.
 */
export function takeRereadNeeded(
  queryClient: QueryClient,
  scope: string
): boolean {
  const entry = scopeFor(queryClient, scope);
  const needed = entry.interruptedRefresh || entry.overlapped;
  entry.interruptedRefresh = false;
  entry.overlapped = false;
  return needed;
}

/**
 * Cancels a read of `queryKey` still in flight as a move settles, and answers
 * whether there was one.
 *
 * A read started while the move was out — a task write's refresh, say — may
 * have captured the order from before the move and land after its answer,
 * putting the old order back with nothing to repair it. Cancelling it lets
 * the answer stand; the caller re-reads, because what that read was fetching
 * for (a count, a field) is still owed.
 */
export async function cancelReadInFlight(
  queryClient: QueryClient,
  queryKey: readonly unknown[]
): Promise<boolean> {
  if (queryClient.getQueryState(queryKey)?.fetchStatus !== 'fetching') {
    return false;
  }
  await queryClient.cancelQueries({ queryKey, exact: true });
  return true;
}
