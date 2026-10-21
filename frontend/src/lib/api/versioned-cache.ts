/**
 * A contact's or journal's cached detail, kept together with its `ETag`.
 *
 * The tag lives in the same cache entry as the body so the two can never
 * drift: a refetch replaces both at once. Components read the bare resource
 * through `select: unwrapResource`; writes read and store the tag through the
 * helpers below, which are the only code that should touch a detail entry.
 *
 * Optimistic updates change `resource` only. The tag is the last version the
 * server confirmed, and only a server response — a write or a refetch — may
 * move it.
 */

import type { QueryClient, QueryKey } from '@tanstack/react-query';

export interface Versioned<T> {
  resource: T;
  etag: string | null;
}

/** `select` for a detail query: components never see the envelope. */
export function unwrapResource<T>(versioned: Versioned<T>): T {
  return versioned.resource;
}

/** The tag a write to this aggregate should send, if its detail was read. */
export function readEtag(
  queryClient: QueryClient,
  key: QueryKey
): string | null {
  return queryClient.getQueryData<Versioned<unknown>>(key)?.etag ?? null;
}

/**
 * Records the version a write committed.
 *
 * A write that returned no tag still replaces the cached one with `null`: the
 * old tag is stale either way, and the next write going out unconditionally
 * beats it being refused for a version this client wrote itself.
 */
export function storeEtag(
  queryClient: QueryClient,
  key: QueryKey,
  etag: string | null
): void {
  queryClient.setQueryData<Versioned<unknown>>(key, cached =>
    cached ? { ...cached, etag } : cached
  );
}

/** Replaces the cached resource and its tag together. */
export function storeVersioned<T>(
  queryClient: QueryClient,
  key: QueryKey,
  resource: T,
  etag: string | null
): void {
  queryClient.setQueryData<Versioned<T>>(key, { resource, etag });
}

/** Rewrites the cached resource, leaving its tag as the server last set it. */
export function updateResource<T>(
  queryClient: QueryClient,
  key: QueryKey,
  update: (resource: T) => T
): void {
  queryClient.setQueryData<Versioned<T>>(key, cached =>
    cached ? { ...cached, resource: update(cached.resource) } : cached
  );
}
