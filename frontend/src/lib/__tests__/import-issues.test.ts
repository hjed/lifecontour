import { describeAddress, skippedReason } from '../import-issues';

const address = {
  street_line_1: '10 Downing St',
  street_line_2: null,
  locality: 'London',
  region: 'London',
  postal_code: 'SW1A 2AA',
  country_code: 'AU',
};

describe('describeAddress', () => {
  it('joins the lines it has', () => {
    expect(describeAddress(address)).toBe(
      '10 Downing St, London, London SW1A 2AA'
    );
    expect(
      describeAddress({ ...address, locality: null, postal_code: null })
    ).toBe('10 Downing St, London');
  });
});

describe('skippedReason', () => {
  it.each([
    ['AU', '“London” isn’t a state or territory of Australia'],
    ['US', '“London” isn’t a state of United States'],
    ['CA', '“London” isn’t a province or territory of Canada'],
  ])('names what %s regions are', (country, reason) => {
    expect(
      skippedReason('unrecognised_region', {
        ...address,
        country_code: country,
      })
    ).toBe(reason);
  });

  it('falls back for a reason it does not know', () => {
    expect(skippedReason('something_new', address)).toBe(
      'It couldn’t be imported'
    );
  });
});
