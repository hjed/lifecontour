/**
 * Hook for building a tree structure from flat journal lists.
 *
 * Shared between JournalList (main list view) and ContactJournals
 * to avoid duplicating tree-building logic.
 */

import { useMemo } from 'react';
import { DisplayJournal } from '@/utils/journalTransformers';

export interface JournalTreeNode {
  journal: DisplayJournal;
  children: JournalTreeNode[];
  hasChildren: boolean;
  isLeaf: boolean;
}

/**
 * Sorts child nodes chronologically ascending (oldest first).
 * If dates are equal, uses the `order` field.
 */
function compareChildNodes(a: JournalTreeNode, b: JournalTreeNode): number {
  const dateA = new Date(a.journal.event_date_range.start).getTime();
  const dateB = new Date(b.journal.event_date_range.start).getTime();

  if (dateA !== dateB) return dateA - dateB;

  const orderA = a.journal.order ?? Number.POSITIVE_INFINITY;
  const orderB = b.journal.order ?? Number.POSITIVE_INFINITY;
  if (orderA !== orderB) return orderA - orderB;

  return String(a.journal.id).localeCompare(String(b.journal.id));
}

/**
 * Build a tree of JournalTreeNodes from a flat list of DisplayJournals.
 *
 * Journals whose parent_id refers to a journal not in the list are promoted
 * to root level (orphan-safe for paginated results).
 *
 * Uses the API-provided `depth` field for accurate hierarchy information
 * regardless of pagination.
 */
export function buildJournalTree(
  journals: DisplayJournal[]
): JournalTreeNode[] {
  if (journals.length === 0) return [];

  const journalIds = new Set(journals.map(j => String(j.id)));
  const nodesById = new Map<string, JournalTreeNode>();

  // Create nodes
  for (const journal of journals) {
    nodesById.set(String(journal.id), {
      journal,
      children: [],
      hasChildren: (journal.children_count ?? 0) > 0,
      isLeaf: (journal.children_count ?? 0) === 0,
    });
  }

  // Link children to parents
  const roots: JournalTreeNode[] = [];
  for (const node of Array.from(nodesById.values())) {
    const parentId =
      node.journal.parent_id !== null && node.journal.parent_id !== undefined
        ? String(node.journal.parent_id)
        : null;

    if (parentId && journalIds.has(parentId)) {
      const parentNode = nodesById.get(parentId);
      if (parentNode) {
        parentNode.children.push(node);
      }
    } else {
      roots.push(node);
    }
  }

  // Sort children of each node
  for (const node of Array.from(nodesById.values())) {
    if (node.children.length > 1) {
      node.children.sort(compareChildNodes);
    }
  }

  return roots;
}

/**
 * React hook that memoises the tree structure from a flat journal list.
 */
export function useJournalTree(journals: DisplayJournal[]): JournalTreeNode[] {
  return useMemo(() => buildJournalTree(journals), [journals]);
}
