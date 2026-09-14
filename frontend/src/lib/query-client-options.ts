/**
 * The application QueryClient's defaults, in a module of their own so a test
 * can build a client that behaves like production.
 *
 * The shared test harness turns retries off, which is right for most hook
 * tests and wrong for any hook whose correctness depends on *not* being
 * retried or refetched on focus.
 */

import type { DefaultOptions } from '@tanstack/react-query';

export const QUERY_CLIENT_DEFAULT_OPTIONS: DefaultOptions = {
  queries: {
    // Stale time: 5 minutes for most data
    staleTime: 5 * 60 * 1000,
    // Cache time: 10 minutes
    gcTime: 10 * 60 * 1000,
    // Retry failed requests 3 times
    retry: 3,
    // Retry delay with exponential backoff
    retryDelay: attemptIndex => Math.min(1000 * 2 ** attemptIndex, 30000),
    // Refetch on window focus for fresh data
    refetchOnWindowFocus: true,
    // Don't refetch on reconnect to avoid excessive requests
    refetchOnReconnect: false,
  },
  mutations: {
    // Retry mutations once on failure
    retry: 1,
    // Retry delay for mutations
    retryDelay: 1000,
  },
};
