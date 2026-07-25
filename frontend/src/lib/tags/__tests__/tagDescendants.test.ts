import { collectDescendantIds } from '../tagDescendants';
import { journalTagView } from '../buildTagTree';
import type { JournalTag } from '@/types/journals';

function tag(id: string, name: string, parentId: string | null = null) {
  return { id, name, color: null, parent_id: parentId } as JournalTag;
}

describe('collectDescendantIds', () => {
  it('returns the direct children of a tag', () => {
    const tags = [
      tag('root', 'Root'),
      tag('a', 'A', 'root'),
      tag('b', 'B', 'root'),
    ];

    expect(collectDescendantIds(tags, 'root', journalTagView)).toEqual(
      new Set(['a', 'b'])
    );
  });

  it('walks the whole subtree, not just one level', () => {
    const tags = [
      tag('root', 'Root'),
      tag('a', 'A', 'root'),
      tag('a1', 'A1', 'a'),
      tag('a1x', 'A1X', 'a1'),
    ];

    expect(collectDescendantIds(tags, 'root', journalTagView)).toEqual(
      new Set(['a', 'a1', 'a1x'])
    );
  });

  it('excludes the tag itself and unrelated branches', () => {
    const tags = [
      tag('root', 'Root'),
      tag('a', 'A', 'root'),
      tag('other', 'Other'),
      tag('other-child', 'Other Child', 'other'),
    ];

    const descendants = collectDescendantIds(tags, 'root', journalTagView);

    expect(descendants.has('root')).toBe(false);
    expect(descendants.has('other')).toBe(false);
    expect(descendants.has('other-child')).toBe(false);
  });

  it('returns an empty set for a leaf tag', () => {
    const tags = [tag('root', 'Root'), tag('a', 'A', 'root')];

    expect(collectDescendantIds(tags, 'a', journalTagView).size).toBe(0);
  });

  it('terminates on a cyclic parent chain rather than looping forever', () => {
    // Data corruption the backend rejects, but the UI must not hang on it.
    const tags = [tag('a', 'A', 'b'), tag('b', 'B', 'a')];

    expect(collectDescendantIds(tags, 'a', journalTagView)).toEqual(
      new Set(['b'])
    );
  });
});
