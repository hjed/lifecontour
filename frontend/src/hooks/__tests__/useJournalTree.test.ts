/**
 * Unit tests for useJournalTree hook and buildJournalTree utility.
 */

import { buildJournalTree } from '@/hooks/useJournalTree';
import { DisplayJournal } from '@/utils/journalTransformers';

function makeDisplayJournal(
  id: string,
  overrides: Partial<DisplayJournal> = {}
): DisplayJournal {
  return {
    id,
    title: `Journal ${id}`,
    content: '',
    event_date_range: {
      start: '2025-01-01T00:00:00Z',
      end: '2025-01-01T01:00:00Z',
    },
    parent_id: null,
    order: null,
    types: [],
    contacts: [],
    tags: [],
    children_count: 0,
    depth: 1,
    ...overrides,
  };
}

describe('buildJournalTree', () => {
  it('returns empty array for empty input', () => {
    expect(buildJournalTree([])).toEqual([]);
  });

  it('returns flat list when all journals are roots', () => {
    const journals = [makeDisplayJournal('1'), makeDisplayJournal('2')];
    const tree = buildJournalTree(journals);

    expect(tree).toHaveLength(2);
    expect(tree[0].journal.id).toBe('1');
    expect(tree[1].journal.id).toBe('2');
    expect(tree[0].children).toEqual([]);
    expect(tree[1].children).toEqual([]);
  });

  it('nests children under their parent', () => {
    const parent = makeDisplayJournal('1', { children_count: 2 });
    const childA = makeDisplayJournal('2', { parent_id: 1, depth: 2 });
    const childB = makeDisplayJournal('3', { parent_id: 1, depth: 2 });
    const tree = buildJournalTree([parent, childA, childB]);

    expect(tree).toHaveLength(1);
    expect(tree[0].journal.id).toBe('1');
    expect(tree[0].hasChildren).toBe(true);
    expect(tree[0].isLeaf).toBe(false);
    expect(tree[0].children).toHaveLength(2);

    const childIds = tree[0].children.map(c => c.journal.id);
    expect(childIds).toContain('2');
    expect(childIds).toContain('3');
  });

  it('builds multi-level tree (root→mid→leaf)', () => {
    const root = makeDisplayJournal('1', { children_count: 1 });
    const mid = makeDisplayJournal('2', {
      parent_id: 1,
      depth: 2,
      children_count: 1,
    });
    const leaf = makeDisplayJournal('3', { parent_id: 2, depth: 3 });
    const tree = buildJournalTree([root, mid, leaf]);

    expect(tree).toHaveLength(1);
    expect(tree[0].children).toHaveLength(1);
    expect(tree[0].children[0].journal.id).toBe('2');
    expect(tree[0].children[0].children).toHaveLength(1);
    expect(tree[0].children[0].children[0].journal.id).toBe('3');
    expect(tree[0].children[0].children[0].isLeaf).toBe(true);
  });

  it('promotes orphans (parent not in list) to root', () => {
    const orphan = makeDisplayJournal('5', { parent_id: 99, depth: 2 });
    const tree = buildJournalTree([orphan]);

    expect(tree).toHaveLength(1);
    expect(tree[0].journal.id).toBe('5');
  });

  it('marks hasChildren correctly from children_count', () => {
    const parentWithDbChildren = makeDisplayJournal('1', {
      children_count: 3,
    });
    const tree = buildJournalTree([parentWithDbChildren]);

    // Has DB children but none in the list
    expect(tree[0].hasChildren).toBe(true);
    expect(tree[0].children).toHaveLength(0);
  });
});
