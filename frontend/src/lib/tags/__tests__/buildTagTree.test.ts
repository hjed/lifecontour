/**
 * @jest-environment jsdom
 */

import { buildTagTree } from '../buildTagTree';
import { TagResource } from '@/types/contacts';

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

describe('buildTagTree', () => {
  it('should return empty array for empty input', () => {
    const result = buildTagTree([]);
    expect(result).toEqual([]);
  });

  it('should return all tags as roots when none have parents', () => {
    const tags = [makeTag('1', 'Work'), makeTag('2', 'Family')];

    const result = buildTagTree(tags);

    expect(result).toHaveLength(2);
    expect(result.map(n => n.tag.attributes.name)).toEqual(['Family', 'Work']);
    expect(result.every(n => n.children.length === 0)).toBe(true);
  });

  it('should nest child tags under their parent', () => {
    const tags = [
      makeTag('1', 'Work'),
      makeTag('2', 'Engineering', 1),
      makeTag('3', 'Design', 1),
    ];

    const result = buildTagTree(tags);

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

    const result = buildTagTree(tags);

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

    const result = buildTagTree(tags);

    expect(result).toHaveLength(2);
    expect(result.map(n => n.tag.attributes.name)).toEqual(['Orphan', 'Work']);
  });

  it('should sort siblings alphabetically at each level', () => {
    const tags = [
      makeTag('1', 'Zebra'),
      makeTag('2', 'Apple'),
      makeTag('3', 'Mango'),
      makeTag('4', 'Zebra-Child-B', 1),
      makeTag('5', 'Zebra-Child-A', 1),
    ];

    const result = buildTagTree(tags);

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

    const result = buildTagTree(tags);

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
