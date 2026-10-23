import { diffAggregate } from '../aggregate-diff';

const LABELS = {
  first_name: 'First name',
  contact_methods: 'Contact methods',
  tags: 'Tags',
};

function contact(
  attributes: Record<string, unknown>,
  relationships: Record<string, unknown> = {}
) {
  return {
    data: {
      id: '1',
      type: 'contacts',
      attributes: { updated_at: '2026-01-01T00:00:00Z', ...attributes },
      relationships,
    },
  };
}

describe('diffAggregate', () => {
  it('names a changed attribute by its label', () => {
    expect(
      diffAggregate(
        contact({ first_name: 'Ada' }),
        contact({ first_name: 'Augusta' }),
        LABELS
      )
    ).toEqual(['First name']);
  });

  it('names a child collection that gained or lost a row', () => {
    expect(
      diffAggregate(
        contact({ contact_methods: [{ id: 'm1' }] }),
        contact({ contact_methods: [{ id: 'm1' }, { id: 'm2' }] }),
        LABELS
      )
    ).toEqual(['Contact methods']);
  });

  it('ignores fields it has no label for', () => {
    expect(
      diffAggregate(
        contact({ first_name: 'Ada', summary: 'old' }),
        contact({ first_name: 'Ada', summary: 'regenerated' }),
        LABELS
      )
    ).toEqual([]);
  });

  it('reports relationships and attributes added on one side only', () => {
    expect(
      diffAggregate(
        contact({}),
        contact({ first_name: 'Ada' }, { tags: { data: [{ id: 't1' }] } }),
        LABELS
      )
    ).toEqual(['First name', 'Tags']);
  });

  it('compares a missing relationships object as empty', () => {
    const before = {
      data: { attributes: { first_name: 'Ada' }, relationships: null },
    };
    const after = {
      data: { attributes: { first_name: 'Augusta' }, relationships: null },
    };

    expect(diffAggregate(before, after, LABELS)).toEqual(['First name']);
  });

  it('reports nothing when there is nothing to compare against', () => {
    expect(diffAggregate(undefined, contact({}), LABELS)).toEqual([]);
  });
});
