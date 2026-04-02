/**
 * Custom hook for managing tag filter state via URL search params.
 *
 * Reads and writes the `tag` search param so that tag-filtered contact
 * list views use the standard `/contacts?tag=<id>` URL pattern.
 */

'use client';

import { useCallback } from 'react';
import type { Route } from 'next';
import { useRouter, useSearchParams, usePathname } from 'next/navigation';

/** Key used in URL search params for the tag filter. */
export const TAG_PARAM = 'tag';

export interface TagFilter {
  /** Current tag ID from URL, or null if no tag filter is active. */
  readonly tagId: string | null;
  /** Navigate to the contacts list filtered by the given tag ID. */
  readonly setTag: (id: string) => void;
  /** Remove the tag filter and navigate to the unfiltered contacts list. */
  readonly clearTag: () => void;
}

export function useTagFilter(): TagFilter {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const tagId = searchParams.get(TAG_PARAM) || null;

  const setTag = useCallback(
    (id: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set(TAG_PARAM, id);
      router.push(`/contacts?${params.toString()}` as Route);
    },
    [router, searchParams]
  );

  const clearTag = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete(TAG_PARAM);
    const qs = params.toString();
    const target = qs ? `${pathname}?${qs}` : '/contacts';
    router.push(target as Route);
  }, [router, searchParams, pathname]);

  return { tagId, setTag, clearTag };
}
