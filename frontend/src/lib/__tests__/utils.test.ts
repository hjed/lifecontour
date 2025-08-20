import { generateDisplayName } from '../utils';

describe('generateDisplayName', () => {
  it('generates full name when both first and last names are provided', () => {
    expect(generateDisplayName('John', 'Doe')).toBe('John Doe');
  });

  it('handles first name only', () => {
    expect(generateDisplayName('John', '')).toBe('John');
  });

  it('handles last name only', () => {
    expect(generateDisplayName('', 'Doe')).toBe('Doe');
  });

  it('handles empty strings for both names', () => {
    expect(generateDisplayName('', '')).toBe('');
  });

  it('trims whitespace from names', () => {
    expect(generateDisplayName('  John  ', '  Doe  ')).toBe('John Doe');
  });

  it('handles whitespace-only names', () => {
    expect(generateDisplayName('   ', '   ')).toBe('');
  });

  it('handles mixed whitespace scenarios', () => {
    expect(generateDisplayName('John', '   ')).toBe('John');
    expect(generateDisplayName('   ', 'Doe')).toBe('Doe');
  });

  it('handles special characters in names', () => {
    expect(generateDisplayName('John-Paul', "O'Connor")).toBe(
      "John-Paul O'Connor"
    );
  });

  it('handles unicode characters', () => {
    expect(generateDisplayName('José', 'García')).toBe('José García');
  });

  it('handles single character names', () => {
    expect(generateDisplayName('J', 'D')).toBe('J D');
  });
});
