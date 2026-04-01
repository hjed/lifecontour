/**
 * Transforms a flat array of TagResource objects into a nested tree structure.
 *
 * Used by the sidebar to render hierarchical tag navigation.
 * Orphaned children (whose parent is not in the input list) are treated as roots.
 * Siblings are sorted alphabetically by name at each level.
 */

import { TagResource } from '@/types/contacts';

export interface TagTreeNode {
  readonly tag: TagResource;
  readonly children: TagTreeNode[];
}

/**
 * Build a tree of TagTreeNode from a flat list of TagResource.
 *
 * @param tags - Flat array of tags, each optionally having `parent_id`.
 * @returns Array of root-level TagTreeNode, sorted alphabetically, with nested children.
 */
export function buildTagTree(tags: TagResource[]): TagTreeNode[] {
  if (tags.length === 0) {
    return [];
  }

  // Index tags by id for O(1) lookup
  const byId = new Map<string, TagTreeNode>();
  for (const tag of tags) {
    byId.set(tag.id, { tag, children: [] });
  }

  const roots: TagTreeNode[] = [];

  for (const tag of tags) {
    const node = byId.get(tag.id)!;
    const parentId = tag.attributes.parent_id;

    if (parentId != null) {
      const parentNode = byId.get(String(parentId));
      if (parentNode) {
        parentNode.children.push(node);
      } else {
        // Orphaned child: parent not in list, treat as root
        roots.push(node);
      }
    } else {
      roots.push(node);
    }
  }

  // Sort siblings alphabetically at each level
  const sortNodes = (nodes: TagTreeNode[]) => {
    nodes.sort((a, b) =>
      a.tag.attributes.name.localeCompare(b.tag.attributes.name)
    );
    for (const node of nodes) {
      if (node.children.length > 0) {
        sortNodes(node.children);
      }
    }
  };

  sortNodes(roots);

  return roots;
}
