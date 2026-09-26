/**
 * Splitting a contact's emails, phones or addresses into the ones in use and
 * the archived ones - values kept for reference that are no longer used.
 */

interface MaybeArchived {
  readonly attributes: { readonly is_archived?: boolean };
}

/** `[inUse, archived]`, each in the order given. */
export function partitionArchived<T extends MaybeArchived>(
  items: readonly T[]
): [T[], T[]] {
  const inUse: T[] = [];
  const archived: T[] = [];
  for (const item of items) {
    (item.attributes.is_archived ? archived : inUse).push(item);
  }
  return [inUse, archived];
}
