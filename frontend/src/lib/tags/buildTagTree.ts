/**
 * Transforms a flat array of tags into a nested tree structure.
 *
 * Used by the sidebar to render hierarchical tag navigation for both tag
 * namespaces. Contact tags arrive as JSON:API `TagResource` objects with
 * integer ids; journal tags arrive as flat, UUID-keyed `JournalTag` objects.
 * Rather than duplicating the algorithm, callers pass a `view` adapter that
 * projects their own shape onto {@link TagTreeView}; nodes keep the original
 * tag so renderers can still read domain-specific fields.
 *
 * Orphaned children (whose parent is not in the input list) are treated as roots.
 * Siblings are sorted alphabetically by name at each level.
 */

import { TagResource } from '@/types/contacts';
import { JournalTag } from '@/types/journals';

/** The minimum a tag must expose for the tree to be built from it. */
export interface TagTreeView {
  readonly id: string;
  readonly name: string;
  readonly parentId: string | null;
}

/** Projects a domain tag onto the shape {@link buildTagTree} needs. */
export type TagTreeAdapter<T> = (tag: T) => TagTreeView;

export interface TagTreeNode<T = TagResource> {
  readonly tag: T;
  readonly children: TagTreeNode<T>[];
}

/** Adapter for contact tags (`GET /api/tags`). */
export const contactTagView: TagTreeAdapter<TagResource> = tag => ({
  id: tag.id,
  name: tag.attributes.name,
  parentId:
    tag.attributes.parent_id == null ? null : String(tag.attributes.parent_id),
});

/** Adapter for journal tags (`GET /api/journals/tags`). */
export const journalTagView: TagTreeAdapter<JournalTag> = tag => ({
  id: tag.id,
  name: tag.name,
  parentId: tag.parent_id ?? null,
});

/**
 * Build a tree of TagTreeNode from a flat list of tags.
 *
 * @param tags - Flat array of tags, each optionally referencing a parent.
 * @param view - Adapter projecting each tag onto {@link TagTreeView}.
 * @returns Array of root-level TagTreeNode, sorted alphabetically, with nested children.
 */
export function buildTagTree<T>(
  tags: readonly T[],
  view: TagTreeAdapter<T>
): TagTreeNode<T>[] {
  if (tags.length === 0) {
    return [];
  }

  // Index tags by id for O(1) lookup
  const byId = new Map<string, TagTreeNode<T>>();
  for (const tag of tags) {
    byId.set(view(tag).id, { tag, children: [] });
  }

  const roots: TagTreeNode<T>[] = [];

  for (const tag of tags) {
    const { id, parentId } = view(tag);
    const node = byId.get(id)!;

    if (parentId == null) {
      roots.push(node);
    } else {
      const parentNode = byId.get(parentId);
      if (parentNode) {
        parentNode.children.push(node);
      } else {
        // Orphaned child: parent not in list, treat as root
        roots.push(node);
      }
    }
  }

  // Sort siblings alphabetically at each level, with cycle detection
  const sortNodes = (nodes: TagTreeNode<T>[], visited = new Set<string>()) => {
    nodes.sort((a, b) => view(a.tag).name.localeCompare(view(b.tag).name));
    for (const node of nodes) {
      const nodeId = view(node.tag).id;
      if (node.children.length > 0 && !visited.has(nodeId)) {
        visited.add(nodeId);
        sortNodes(node.children, visited);
      }
    }
  };

  sortNodes(roots);

  return roots;
}
