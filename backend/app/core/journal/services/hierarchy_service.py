"""Hierarchy service for journal tree-shaping and depth computation.

Provides centralised logic for building hierarchical views of journals,
used by both API controllers and MCP tools to avoid duplicating tree logic.
"""

from __future__ import annotations

import dataclasses

from core_shared.models.journals import Journal

from app.core.journal.models.repositories import JournalRepository


@dataclasses.dataclass(frozen=True)
class HierarchyNode:
    """A journal enriched with hierarchy metadata for display.

    Attributes:
        journal: The underlying journal entity.
        depth: Depth in the hierarchy (1 = root, 2 = first-level child, etc.).
        children_count: Number of direct children (from DB).
        has_children: Whether this journal has any children.
        is_leaf: Whether this journal is a leaf node (no children).
        children: Nested child nodes (populated when tree is built in-memory).
    """

    journal: Journal
    depth: int
    children_count: int
    has_children: bool
    is_leaf: bool
    children: list[HierarchyNode] = dataclasses.field(default_factory=list)


class HierarchyService:
    """Centralised hierarchy logic for journal tree-shaping.

    All methods are either static or class methods since the service holds no
    state — it operates on data passed in by callers.
    """

    @staticmethod
    async def compute_depth_map(
        journal_ids: list[int],
        repo: JournalRepository,
    ) -> dict[int, int]:
        """Compute the depth of each journal using DB queries.

        Uses the repository's ``get_depth()`` method per journal, which is
        robust against paginated results where parent journals may not be
        present in the current page.

        Args:
            journal_ids: IDs of journals to compute depth for.
            repo: Journal repository for DB access.

        Returns:
            Mapping of journal_id → depth (1-based).
        """
        if not journal_ids:
            return {}

        depth_map: dict[int, int] = {}
        for jid in journal_ids:
            depth_map[jid] = await repo.get_depth(jid)
        return depth_map

    @staticmethod
    def build_tree_nodes(
        journals: list[Journal],
        children_counts: dict[int, int],
        depth_map: dict[int, int],
    ) -> list[HierarchyNode]:
        """Build a tree of HierarchyNodes from a flat journal list.

        Journals whose parent_id refers to a journal **not** in the list are
        promoted to root level (orphan-safe behaviour for paginated results).

        Args:
            journals: Flat list of journals (may include parents and children).
            children_counts: Mapping of journal_id → direct children count.
            depth_map: Mapping of journal_id → depth (1-based).

        Returns:
            List of root-level HierarchyNodes with children nested inline.
        """
        if not journals:
            return []

        # Index journals by ID for parent lookups
        journal_ids_in_list = {j.id for j in journals if j.id is not None}

        # Create HierarchyNode for each journal
        nodes_by_id: dict[int, HierarchyNode] = {}
        for journal in journals:
            if journal.id is None:
                continue
            jid = journal.id
            count = children_counts.get(jid, 0)
            node = HierarchyNode(
                journal=journal,
                depth=depth_map.get(jid, 1),
                children_count=count,
                has_children=count > 0,
                is_leaf=count == 0,
                children=[],
            )
            nodes_by_id[jid] = node

        # Build tree by linking children to parents
        roots: list[HierarchyNode] = []
        for node in nodes_by_id.values():
            parent_id = node.journal.parent_id
            if parent_id is not None and parent_id in journal_ids_in_list:
                # Parent is in the list — attach as child
                parent_node = nodes_by_id[parent_id]
                # Since HierarchyNode is frozen, children list is mutable
                # (default_factory creates a new list)
                parent_node.children.append(node)
            else:
                # Root journal or orphan (parent not in list)
                roots.append(node)

        return roots
