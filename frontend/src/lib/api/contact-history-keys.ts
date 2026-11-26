/**
 * Query keys for a contact's activity history.
 *
 * In a module of their own, as `journal-keys.ts` is, so the task clients can
 * name them: `contacts.ts` imports `taskKeys` from `tasks.ts`, and the reverse
 * import would close a cycle. A task write that puts a row on a contact's feed
 * — creating a task with contacts, linking or unlinking one, moving a task
 * between lists (the rows are labelled with the list) — names these.
 */
export const historyKeys = {
  all: ['contact-history'] as const,
  list: (contactId: string, page?: number, limit?: number) =>
    [...historyKeys.all, contactId, { page, limit }] as const,
};

/** The filter a task write passes to refresh every contact's feed. */
export const REFRESH_CONTACT_HISTORY = { queryKey: historyKeys.all };
