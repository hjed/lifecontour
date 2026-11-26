import { moveAfter, moveToIndex, orderByIds } from '@/lib/api/cached-order';

interface Row {
  id: string;
  label: string;
}

const rows = (...ids: string[]): Row[] =>
  ids.map(id => ({ id, label: `row ${id}` }));

const ids = (items: readonly Row[]) => items.map(item => item.id);

describe('moveToIndex', () => {
  it('moves a row to the index, counting without it', () => {
    expect(ids(moveToIndex(rows('a', 'b', 'c', 'd'), 'a', 2))).toEqual([
      'b',
      'c',
      'a',
      'd',
    ]);
    expect(ids(moveToIndex(rows('a', 'b', 'c'), 'c', 0))).toEqual([
      'c',
      'a',
      'b',
    ]);
  });

  it('puts an index past the end at the bottom, as the server does', () => {
    expect(ids(moveToIndex(rows('a', 'b', 'c'), 'a', 99))).toEqual([
      'b',
      'c',
      'a',
    ]);
  });

  it('leaves the order alone for a row it does not hold', () => {
    const before = rows('a', 'b');
    const after = moveToIndex(before, 'z', 0);

    expect(ids(after)).toEqual(['a', 'b']);
    expect(after).not.toBe(before);
  });
});

describe('moveAfter', () => {
  it('moves a row directly after its anchor', () => {
    expect(ids(moveAfter(rows('a', 'b', 'c', 'd'), 'a', 'c'))).toEqual([
      'b',
      'c',
      'a',
      'd',
    ]);
    expect(ids(moveAfter(rows('a', 'b', 'c', 'd'), 'd', 'a'))).toEqual([
      'a',
      'd',
      'b',
      'c',
    ]);
  });

  it('moves a row to the top when there is no anchor', () => {
    expect(ids(moveAfter(rows('a', 'b', 'c'), 'c', null))).toEqual([
      'c',
      'a',
      'b',
    ]);
  });

  it('leaves the order alone when the row or its anchor is not held', () => {
    expect(ids(moveAfter(rows('a', 'b'), 'z', null))).toEqual(['a', 'b']);
    expect(ids(moveAfter(rows('a', 'b'), 'a', 'z'))).toEqual(['a', 'b']);
  });
});

describe('orderByIds', () => {
  it('re-orders rows by the ids, keeping each row as it is', () => {
    const before = rows('a', 'b', 'c');
    const { items, matched } = orderByIds(before, ['c', 'a', 'b']);

    expect(ids(items)).toEqual(['c', 'a', 'b']);
    // The rows themselves are untouched — the order is all that moved, so a
    // field patched in the meantime is never overwritten.
    expect(items[0]).toBe(before[2]);
    expect(matched).toBe(true);
  });

  it('keeps rows the ids do not name at the end, in their own order', () => {
    const { items, matched } = orderByIds(rows('a', 'b', 'c', 'd'), ['d', 'b']);

    expect(ids(items)).toEqual(['d', 'b', 'a', 'c']);
    expect(matched).toBe(false);
  });

  it('reports ids it holds no row for, and invents none', () => {
    const { items, matched } = orderByIds(rows('a', 'b'), ['b', 'x', 'a']);

    expect(ids(items)).toEqual(['b', 'a']);
    expect(matched).toBe(false);
  });
});
