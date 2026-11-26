/**
 * Re-ordering cached rows without rewriting them.
 *
 * The list page's drags change *where* a row sits and nothing else, while a
 * status tick may be patching that same row's attributes at the same moment.
 * So every helper here moves the row objects it is given and never builds new
 * ones: an optimistic move, the re-sort to the server's answer and the
 * rollback all keep whatever each row currently says, and a concurrent patch
 * survives all three.
 */

/** Anything with a resource id. */
interface Identified {
  readonly id: string;
}

/**
 * Moves one row to `index`, counted among the other rows. An index past the
 * end puts it at the bottom, as the server does. A row it does not hold leaves
 * the order as it was.
 */
export function moveToIndex<T extends Identified>(
  items: readonly T[],
  id: string,
  index: number
): T[] {
  const moving = items.find(item => item.id === id);
  if (!moving) return [...items];

  const rest = items.filter(item => item !== moving);
  const at = Math.max(0, Math.min(index, rest.length));
  return [...rest.slice(0, at), moving, ...rest.slice(at)];
}

/**
 * Moves one row directly after `afterId`, or to the top when that is `null`.
 * If either the row or its anchor is not held, the order is left as it was:
 * there is no place to put it that the server would agree with.
 */
export function moveAfter<T extends Identified>(
  items: readonly T[],
  id: string,
  afterId: string | null
): T[] {
  if (afterId === null) return moveToIndex(items, id, 0);

  const moving = items.find(item => item.id === id);
  const rest = items.filter(item => item !== moving);
  const anchor = rest.findIndex(item => item.id === afterId);
  if (!moving || anchor === -1) return [...items];

  return [...rest.slice(0, anchor + 1), moving, ...rest.slice(anchor + 1)];
}

/**
 * Re-orders rows by `ids`, the order the server answered with.
 *
 * Rows the ids do not name stay at the end in their own order (a task ticked
 * done in the meantime, say), and ids with no row are skipped — nothing is
 * invented or dropped. `matched` says whether the two named the same set; when
 * they did not, the cache has drifted from the server and the caller should
 * re-read rather than trust the result.
 */
export function orderByIds<T extends Identified>(
  items: readonly T[],
  ids: readonly string[]
): { items: T[]; matched: boolean } {
  const byId = new Map(items.map(item => [item.id, item]));
  const named = ids.flatMap(id => byId.get(id) ?? []);
  const unnamed = items.filter(item => !ids.includes(item.id));

  return {
    items: [...named, ...unnamed],
    matched: unnamed.length === 0 && named.length === ids.length,
  };
}
