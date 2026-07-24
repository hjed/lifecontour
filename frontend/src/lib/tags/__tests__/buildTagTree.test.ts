/**
 * @jest-environment jsdom
 */

import { buildTagTree, contactTagView, journalTagView } from '../buildTagTree';
import type { TagResource } from '@/types/contacts';
import type { JournalTag } from '@/types/journals';

/**
 * Factory helper to create TagResource test fixtures.
 */
function makeTag(
  id: string,
  name: string,
  parentId: number | null = null
): TagResource {
  return {
    type: 'tags',
    id,
    attributes: {
      name,
      parent_id: parentId,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    },
  };
}

/**
 * Factory helper for the flat journal tag shape returned by `useJournalTags`.
 */
function makeJournalTag(
  id: string,
  name: string,
  parentId: string | null = null
): JournalTag {
  return { id, name, color: '#3B82F6', parent_id: parentId };
}

describe('buildTagTree', () => {
  describe('contact tags (JSON:API resources)', () => {
    it('should return empty array for empty input', () => {
      const result = buildTagTree([], contactTagView);
      expect(result).toEqual([]);
    });

    it('should return all tags as roots when none have parents', () => {
      const tags = [makeTag('1', 'Work'), makeTag('2', 'Family')];

      const result = buildTagTree(tags, contactTagView);

      expect(result).toHaveLength(2);
      expect(result.map(n => n.tag.attributes.name)).toEqual([
        'Family',
        'Work',
      ]);
      expect(result.every(n => n.children.length === 0)).toBe(true);
    });

    it('should nest child tags under their parent', () => {
      const tags = [
        makeTag('1', 'Work'),
        makeTag('2', 'Engineering', 1),
        makeTag('3', 'Design', 1),
      ];

      const result = buildTagTree(tags, contactTagView);

      expect(result).toHaveLength(1);
      expect(result[0].tag.attributes.name).toBe('Work');
      expect(result[0].children).toHaveLength(2);
      expect(result[0].children.map(n => n.tag.attributes.name)).toEqual([
        'Design',
        'Engineering',
      ]);
    });

    it('should handle multi-level nesting', () => {
      const tags = [
        makeTag('1', 'Work'),
        makeTag('2', 'Engineering', 1),
        makeTag('3', 'Frontend', 2),
      ];

      const result = buildTagTree(tags, contactTagView);

      expect(result).toHaveLength(1);
      const work = result[0];
      expect(work.tag.attributes.name).toBe('Work');
      expect(work.children).toHaveLength(1);

      const engineering = work.children[0];
      expect(engineering.tag.attributes.name).toBe('Engineering');
      expect(engineering.children).toHaveLength(1);
      expect(engineering.children[0].tag.attributes.name).toBe('Frontend');
      expect(engineering.children[0].children).toHaveLength(0);
    });

    it('should treat orphaned children as root nodes', () => {
      // parent_id=99 does not exist in the list
      const tags = [makeTag('1', 'Work'), makeTag('2', 'Orphan', 99)];

      const result = buildTagTree(tags, contactTagView);

      expect(result).toHaveLength(2);
      expect(result.map(n => n.tag.attributes.name)).toEqual([
        'Orphan',
        'Work',
      ]);
    });

    it('should sort siblings alphabetically at each level', () => {
      const tags = [
        makeTag('1', 'Zebra'),
        makeTag('2', 'Apple'),
        makeTag('3', 'Mango'),
        makeTag('4', 'Zebra-Child-B', 1),
        makeTag('5', 'Zebra-Child-A', 1),
      ];

      const result = buildTagTree(tags, contactTagView);

      // Root level sorted
      expect(result.map(n => n.tag.attributes.name)).toEqual([
        'Apple',
        'Mango',
        'Zebra',
      ]);

      // Children sorted
      const zebra = result[2];
      expect(zebra.children.map(n => n.tag.attributes.name)).toEqual([
        'Zebra-Child-A',
        'Zebra-Child-B',
      ]);
    });

    it('should handle mixed roots and nested tags', () => {
      const tags = [
        makeTag('1', 'Work'),
        makeTag('2', 'Family'),
        makeTag('3', 'Engineering', 1),
        makeTag('4', 'Parents', 2),
        makeTag('5', 'Friends'),
      ];

      const result = buildTagTree(tags, contactTagView);

      expect(result).toHaveLength(3);
      expect(result.map(n => n.tag.attributes.name)).toEqual([
        'Family',
        'Friends',
        'Work',
      ]);

      const family = result[0];
      expect(family.children).toHaveLength(1);
      expect(family.children[0].tag.attributes.name).toBe('Parents');

      const work = result[2];
      expect(work.children).toHaveLength(1);
      expect(work.children[0].tag.attributes.name).toBe('Engineering');
    });
  });

  describe('journal tags (flat UUID-keyed shape)', () => {
    it('should nest child tags under their parent', () => {
      const tags = [
        makeJournalTag('uuid-work', 'Work'),
        makeJournalTag('uuid-eng', 'Engineering', 'uuid-work'),
        makeJournalTag('uuid-design', 'Design', 'uuid-work'),
      ];

      const result = buildTagTree(tags, journalTagView);

      expect(result).toHaveLength(1);
      expect(result[0].tag.name).toBe('Work');
      expect(result[0].children.map(n => n.tag.name)).toEqual([
        'Design',
        'Engineering',
      ]);
    });

    it('should preserve the source tag on each node', () => {
      const tags = [makeJournalTag('uuid-work', 'Work')];

      const result = buildTagTree(tags, journalTagView);

      // The node carries the original JournalTag, not a normalised copy, so
      // callers can still read domain-specific fields such as `color`.
      expect(result[0].tag).toBe(tags[0]);
      expect(result[0].tag.color).toBe('#3B82F6');
    });

    it('should handle multi-level nesting', () => {
      const tags = [
        makeJournalTag('uuid-work', 'Work'),
        makeJournalTag('uuid-eng', 'Engineering', 'uuid-work'),
        makeJournalTag('uuid-fe', 'Frontend', 'uuid-eng'),
      ];

      const result = buildTagTree(tags, journalTagView);

      const engineering = result[0].children[0];
      expect(engineering.tag.name).toBe('Engineering');
      expect(engineering.children[0].tag.name).toBe('Frontend');
      expect(engineering.children[0].children).toHaveLength(0);
    });

    it('should treat orphaned children as root nodes', () => {
      const tags = [
        makeJournalTag('uuid-work', 'Work'),
        makeJournalTag('uuid-orphan', 'Orphan', 'uuid-missing'),
      ];

      const result = buildTagTree(tags, journalTagView);

      expect(result.map(n => n.tag.name)).toEqual(['Orphan', 'Work']);
    });

    it('should treat a tag with an undefined parent_id as a root', () => {
      // `JournalTag.parent_id` is optional, so it can be absent rather than null.
      const tags: JournalTag[] = [{ id: 'uuid-work', name: 'Work' }];

      const result = buildTagTree(tags, journalTagView);

      expect(result).toHaveLength(1);
      expect(result[0].tag.name).toBe('Work');
    });

    it('should sort siblings alphabetically at each level', () => {
      const tags = [
        makeJournalTag('uuid-z', 'Zebra'),
        makeJournalTag('uuid-a', 'Apple'),
        makeJournalTag('uuid-m', 'Mango'),
        makeJournalTag('uuid-zb', 'Zebra-Child-B', 'uuid-z'),
        makeJournalTag('uuid-za', 'Zebra-Child-A', 'uuid-z'),
      ];

      const result = buildTagTree(tags, journalTagView);

      expect(result.map(n => n.tag.name)).toEqual(['Apple', 'Mango', 'Zebra']);
      expect(result[2].children.map(n => n.tag.name)).toEqual([
        'Zebra-Child-A',
        'Zebra-Child-B',
      ]);
    });

    it('should terminate on cyclic parent references', () => {
      // Corrupt data: two tags each claiming the other as parent. Neither is a
      // root, so the tree is empty — but building it must not recurse forever.
      const tags = [
        makeJournalTag('uuid-a', 'A', 'uuid-b'),
        makeJournalTag('uuid-b', 'B', 'uuid-a'),
      ];

      const result = buildTagTree(tags, journalTagView);

      expect(result).toEqual([]);
    });
  });
});
