import { listCountries } from '../countries';

describe('listCountries', () => {
  it('names each country and sorts by name', () => {
    const countries = listCountries();
    const names = countries.map(country => country.name);

    expect(countries).toContainEqual({ code: 'NZ', name: 'New Zealand' });
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b, 'en')));
  });

  it('leaves out phone regions that are not ISO 3166-1 countries', () => {
    const codes = listCountries().map(country => country.code);

    expect(codes).not.toContain('XK');
    expect(codes).not.toContain('AC');
    expect(codes).not.toContain('TA');
  });
});
