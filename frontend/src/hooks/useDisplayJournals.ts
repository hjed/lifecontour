import { useMemo } from 'react';
import { JournalResource } from '@/types/journals';
import {
  DisplayJournal,
  transformJournalForDisplay,
} from '@/utils/journalTransformers';

// Re-export DisplayJournal type for backward compatibility
export type { DisplayJournal };

/**
 * Custom hook to transform journal data for display
 * Eliminates duplicate journal transformation logic across pages
 * Supports optional search highlighting for search results
 */
export function useDisplayJournals(
  journals: JournalResource[] | undefined,
  shouldUseSearch = false
): DisplayJournal[] {
  return useMemo(() => {
    if (!journals) return [];

    return journals.map(journal =>
      transformJournalForDisplay(journal, shouldUseSearch)
    );
  }, [journals, shouldUseSearch]);
}
