/**
 * Which journal, if any, the current page is showing — the New dialog's
 * pre-fill for a task's creating journal.
 */

import { journalIdFromPath } from '../viewed-journal';

describe('journalIdFromPath', () => {
  it('reads the id of a journal page', () => {
    expect(journalIdFromPath('/journals/42')).toBe('42');
  });

  it.each([
    ['a trailing slash', '/journals/42/'],
    ['the new-journal page', '/journals/new'],
    ['a series page', '/journals/series/3'],
    ['the outdoor logbook', '/journals/outdoor-logbook'],
    ['the journals list', '/journals'],
    ['a contact page', '/contacts/4'],
    ['home', '/'],
    ['nothing at all', null],
  ])('is null for %s', (_label, pathname) => {
    expect(journalIdFromPath(pathname)).toBeNull();
  });
});
