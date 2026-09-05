/**
 * Splitting a display name for an avatar's initials.
 *
 * Contacts reach some surfaces as a single display name and `ContactAvatar`
 * wants the parts; the split is shared so a task row and an agenda row derive
 * the same initials for the same person.
 */

import { nameParts } from '../contact-names';

describe('nameParts', () => {
  it('splits a two-part name into first and last', () => {
    expect(nameParts('Sam Taylor')).toEqual({ first: 'Sam', last: 'Taylor' });
  });

  it('keeps everything after the first space as the surname', () => {
    expect(nameParts('Mary Anne van der Berg')).toEqual({
      first: 'Mary',
      last: 'Anne van der Berg',
    });
  });

  it('leaves the surname empty for a single name', () => {
    expect(nameParts('Cher')).toEqual({ first: 'Cher', last: '' });
  });

  it('ignores surrounding and repeated whitespace', () => {
    expect(nameParts('  Sam   Taylor ')).toEqual({
      first: 'Sam',
      last: 'Taylor',
    });
  });

  it('yields two empty parts for an empty name', () => {
    expect(nameParts('')).toEqual({ first: '', last: '' });
  });
});
