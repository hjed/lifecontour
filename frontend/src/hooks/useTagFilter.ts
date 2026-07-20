/**
 * Custom hook for managing tag filter state via URL search params.
 *
 * Reads and writes the `tag` search param so that tag-filtered list views use
 * the standard `<basePath>?tag=<id>` URL pattern. Used by `/contacts` (the
 * default base path) and `/journals`.
 */

'use client';

import { useCallback } from 'react';
import type { Route } from 'next';
import { useRouter, useSearchParams, usePathname } from 'next/navigation';

/** Key used in URL search params for the tag filter. */
export const TAG_PARAM = 'tag';

/**
 * List routes that support tag filtering.
 *
 * Deliberately a closed union rather than `string`: the base path is
 * concatenated into a `router.push` target, and a caller-supplied path would
 * make that navigation an unconstrained redirect sink.
 */
export type TagFilterBasePath = '/contacts' | '/journals';

export interface TagFilter {
  /** Current tag ID from URL, or null if no tag filter is active. */
  readonly tagId: string | null;
  /** Navigate to the list filtered by the given tag ID. */
  readonly setTag: (id: string) => void;
  /** Remove the tag filter and navigate to the unfiltered list. */
  readonly clearTag: () => void;
}

/**
 * @param basePath List route the tag filter navigates to (defaults to `/contacts`).
 */
export function useTagFilter(
  basePath: TagFilterBasePath = '/contacts'
): TagFilter {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const tagId = searchParams.get(TAG_PARAM) || null;

  const setTag = useCallback(
    (id: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set(TAG_PARAM, id);
      router.push(`${basePath}?${params.toString()}` as Route);
    },
    [router, searchParams, basePath]
  );

  const clearTag = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete(TAG_PARAM);
    const qs = params.toString();
    const target = qs ? `${pathname}?${qs}` : basePath;
    router.push(target as Route);
  }, [router, searchParams, pathname, basePath]);

  return { tagId, setTag, clearTag };
}
