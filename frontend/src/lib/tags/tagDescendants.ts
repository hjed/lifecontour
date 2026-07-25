/**
 * Collects the ids beneath a tag in a flat, parent-referencing tag list.
 *
 * Used by the tag management dialogs to keep a tag's own subtree out of the
 * parent (and, later, merge target) dropdowns: re-parenting a tag under its own
 * descendant would create a cycle, which the backend rejects with a 400. This
 * turns that into an option the user is never offered.
 *
 * Shares the {@link TagTreeAdapter} projection with `buildTagTree` so both
 * namespaces can use it.
 */

import type { TagTreeAdapter } from './buildTagTree';

export function collectDescendantIds<T>(
  tags: readonly T[],
  rootId: string,
  view: TagTreeAdapter<T>
): Set<string> {
  const childrenByParent = new Map<string, string[]>();
  for (const tag of tags) {
    const { id, parentId } = view(tag);
    if (parentId == null) continue;
    const siblings = childrenByParent.get(parentId);
    if (siblings) {
      siblings.push(id);
    } else {
      childrenByParent.set(parentId, [id]);
    }
  }

  const descendants = new Set<string>();
  const queue = [...(childrenByParent.get(rootId) ?? [])];

  while (queue.length > 0) {
    const id = queue.pop()!;
    // Guards against a corrupt cyclic parent chain looping forever.
    if (id === rootId || descendants.has(id)) continue;
    descendants.add(id);
    queue.push(...(childrenByParent.get(id) ?? []));
  }

  return descendants;
}
