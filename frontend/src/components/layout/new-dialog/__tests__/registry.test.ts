/**
 * @jest-environment jsdom
 */

import { NEW_ENTITY_TYPES } from '../registry';

jest.mock('@/lib/api/contacts', () => ({
  useCreateContact: jest.fn(),
}));
jest.mock('@/components/journals/NewJournalPanel', () => ({
  NewJournalPanel: () => null,
}));

describe('NEW_ENTITY_TYPES', () => {
  it('gives every type a unique id', () => {
    const ids = NEW_ENTITY_TYPES.map(type => type.id);

    expect(new Set(ids).size).toBe(ids.length);
  });

  it('gives every type a label, an icon and a panel', () => {
    for (const type of NEW_ENTITY_TYPES) {
      expect(type.label.trim()).not.toBe('');
      expect(type.icon).toBeTruthy();
      expect(type.Panel).toBeTruthy();
    }
  });

  it('offers Journal then Contact, in the specification order', () => {
    expect(NEW_ENTITY_TYPES.map(type => type.id)).toEqual([
      'journal',
      'contact',
    ]);
  });
});
