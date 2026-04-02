"""Unit tests for HierarchyService (TDD - Red Phase).

Tests the hierarchy service's depth computation and tree-building logic.
Uses mock repository to avoid database dependency.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals import EventDateRange, Journal

from app.core.journal.services.hierarchy_service import (
    HierarchyNode,
    HierarchyService,
)


def _make_journal(
    journal_id: int,
    title: str = "Test",
    parent_id: int | None = None,
) -> Journal:
    """Create a minimal Journal for testing."""
    now = datetime.now(UTC)
    return Journal(
        id=journal_id,
        user_id="test-user",
        title=title,
        content="",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=1),
        ),
        parent_id=parent_id,
    )


@pytest.mark.unit
class TestComputeDepthMap:
    """Tests for HierarchyService.compute_depth_map."""

    async def test_compute_depth_map_single_root(self):
        """Single root journal gets depth 1."""
        repo = AsyncMock()
        repo.get_depth.return_value = 1

        result = await HierarchyService.compute_depth_map([1], repo)

        assert result == {1: 1}
        repo.get_depth.assert_called_once_with(1)

    async def test_compute_depth_map_parent_child(self):
        """Parent gets depth 1, child gets depth 2."""
        repo = AsyncMock()
        repo.get_depth.side_effect = lambda jid: {1: 1, 2: 2}[jid]

        result = await HierarchyService.compute_depth_map([1, 2], repo)

        assert result == {1: 1, 2: 2}

    async def test_compute_depth_map_three_levels(self):
        """Root→L1→L2 returns depths 1, 2, 3."""
        repo = AsyncMock()
        repo.get_depth.side_effect = lambda jid: {1: 1, 2: 2, 3: 3}[jid]

        result = await HierarchyService.compute_depth_map([1, 2, 3], repo)

        assert result == {1: 1, 2: 2, 3: 3}

    async def test_compute_depth_map_multiple_roots(self):
        """Two independent roots both get depth 1."""
        repo = AsyncMock()
        repo.get_depth.side_effect = lambda jid: {10: 1, 20: 1}[jid]

        result = await HierarchyService.compute_depth_map([10, 20], repo)

        assert result == {10: 1, 20: 1}

    async def test_compute_depth_map_empty(self):
        """Empty list returns empty map without calling repo."""
        repo = AsyncMock()

        result = await HierarchyService.compute_depth_map([], repo)

        assert result == {}
        repo.get_depth.assert_not_called()


@pytest.mark.unit
class TestBuildTreeNodes:
    """Tests for HierarchyService.build_tree_nodes."""

    def test_build_tree_nodes_flat_list(self):
        """All journals with no parent_id produce flat list of root nodes."""
        j1 = _make_journal(1, "Root A")
        j2 = _make_journal(2, "Root B")
        children_counts = {1: 0, 2: 0}
        depth_map = {1: 1, 2: 1}

        nodes = HierarchyService.build_tree_nodes([j1, j2], children_counts, depth_map)

        assert len(nodes) == 2
        assert all(isinstance(n, HierarchyNode) for n in nodes)
        assert all(n.depth == 1 for n in nodes)
        assert all(n.is_leaf for n in nodes)
        assert all(not n.has_children for n in nodes)
        assert all(n.children == [] for n in nodes)

    def test_build_tree_nodes_nested(self):
        """Parent with 2 children produces correct tree structure."""
        parent = _make_journal(1, "Parent")
        child_a = _make_journal(2, "Child A", parent_id=1)
        child_b = _make_journal(3, "Child B", parent_id=1)
        children_counts = {1: 2, 2: 0, 3: 0}
        depth_map = {1: 1, 2: 2, 3: 2}

        nodes = HierarchyService.build_tree_nodes(
            [parent, child_a, child_b], children_counts, depth_map
        )

        # Only 1 root node
        assert len(nodes) == 1
        root = nodes[0]
        assert root.journal.id == 1
        assert root.depth == 1
        assert root.children_count == 2
        assert root.has_children is True
        assert root.is_leaf is False

        # Children nested under root
        assert len(root.children) == 2
        child_ids = {c.journal.id for c in root.children}
        assert child_ids == {2, 3}
        assert all(c.depth == 2 for c in root.children)
        assert all(c.is_leaf for c in root.children)

    def test_build_tree_nodes_multi_level(self):
        """3-level hierarchy: root→mid→leaf with correct nesting and depth."""
        root = _make_journal(1, "Root")
        mid = _make_journal(2, "Mid", parent_id=1)
        leaf = _make_journal(3, "Leaf", parent_id=2)
        children_counts = {1: 1, 2: 1, 3: 0}
        depth_map = {1: 1, 2: 2, 3: 3}

        nodes = HierarchyService.build_tree_nodes(
            [root, mid, leaf], children_counts, depth_map
        )

        assert len(nodes) == 1
        root_node = nodes[0]
        assert root_node.depth == 1
        assert root_node.children_count == 1

        mid_node = root_node.children[0]
        assert mid_node.journal.id == 2
        assert mid_node.depth == 2
        assert mid_node.children_count == 1
        assert mid_node.has_children is True

        leaf_node = mid_node.children[0]
        assert leaf_node.journal.id == 3
        assert leaf_node.depth == 3
        assert leaf_node.is_leaf is True
        assert leaf_node.children == []

    def test_build_tree_nodes_orphan_child_stays_at_top(self):
        """Child whose parent is not in the list appears as root-level node."""
        child = _make_journal(5, "Orphan", parent_id=99)
        children_counts = {5: 0}
        depth_map = {5: 2}  # Depth from DB says it's a child

        nodes = HierarchyService.build_tree_nodes([child], children_counts, depth_map)

        # Orphan appears at top level since parent 99 is not in the list
        assert len(nodes) == 1
        assert nodes[0].journal.id == 5
        assert nodes[0].depth == 2

    def test_build_tree_nodes_empty(self):
        """Empty journal list returns empty list."""
        nodes = HierarchyService.build_tree_nodes([], {}, {})
        assert nodes == []
