/**
 * The journal domain's React Query keys.
 *
 * Split out of `journals.ts` so that **`tasks.ts` can name a journal namespace
 * without importing the journal client**. The two clients genuinely depend on
 * each other's caches — a journal write can change a task's embedded refs, and
 * a task write can change the journal list's `tasks_due_count` — but a runtime
 * import cycle between the two modules is not a safe way to express that.
 *
 * It was tried and it broke: with `journals.ts` importing `taskKeys` and
 * `tasks.ts` importing `journalKeys`, a test that partially mocks the journal
 * client through `jest.requireActual` re-enters `journals.ts` while its own
 * top-level `const`s are still in their temporal dead zone, and the suite fails
 * with `Cannot access 'calendarKeys' before initialization`. Keys have no
 * dependencies of their own, so lifting them here removes the cycle rather than
 * papering over it.
 *
 * `journals.ts` re-exports `journalKeys`, so every existing import of it keeps
 * working and this file needs no call-site churn.
 */

import type { JournalFilters } from '@/types/journals';

import type { ContactJournalsFilters } from './journals';

export const journalKeys = {
  all: ['journals'] as const,
  lists: () => [...journalKeys.all, 'list'] as const,
  list: (filters: JournalFilters) => [...journalKeys.lists(), filters] as const,
  infiniteLists: () => [...journalKeys.lists(), 'infinite'] as const,
  infiniteList: (
    filters: JournalFilters,
    options?: { chunkDays?: number; anchorDate?: string }
  ) => [...journalKeys.infiniteLists(), filters, options] as const,
  details: () => [...journalKeys.all, 'detail'] as const,
  detail: (id: string) => [...journalKeys.details(), id] as const,
  search: (query: string) => [...journalKeys.all, 'search', query] as const,
  /**
   * The future-journal options behind a due-journal picker.
   *
   * `today` and `timezone` are part of the key rather than incidental inputs:
   * the answer is "which journals are still ahead of the user", so a result
   * cached yesterday, or judged in a zone they have since changed, is a
   * different answer to a different question.
   */
  future: (params: { search: string; today: string; timezone: string }) =>
    [...journalKeys.all, 'future', params] as const,
  contactJournals: (contactId: string, filters?: ContactJournalsFilters) =>
    [...journalKeys.all, 'contact', contactId, filters] as const,
};
