/**
 * @jest-environment jsdom
 */

import { render, screen, within } from '@testing-library/react';
import { MockImage } from '@/test-utils/mock-image';
import {
  ContactAvatarStack,
  type ContactAvatarStackPerson,
} from '../ContactAvatarStack';

const NOUN = { one: 'contact', many: 'contacts' } as const;

function person(id: number, name: string): ContactAvatarStackPerson {
  return { id, name };
}

const SAM = person(1, 'Sam Taylor');
const ALEX = person(2, 'Alex Chen');
const PRIYA = person(3, 'Priya Patel');
const JORDAN = person(4, 'Jordan Lee');
const KIM = person(5, 'Kim Nguyen');

function renderStack(people: readonly ContactAvatarStackPerson[]) {
  return render(
    <ContactAvatarStack
      people={people}
      label='Contacts'
      noun={NOUN}
      testId='stack'
    />
  );
}

describe('ContactAvatarStack', () => {
  let originalImage: typeof window.Image;

  beforeEach(() => {
    originalImage = window.Image;
    window.Image = MockImage as unknown as typeof window.Image;
  });

  afterEach(() => {
    window.Image = originalImage;
  });

  it('renders nothing for nobody', () => {
    const { container } = renderStack([]);

    expect(container).toBeEmptyDOMElement();
  });

  it('is a list, named by its label, of one named avatar per person', () => {
    renderStack([SAM, ALEX]);

    const list = screen.getByRole('list', { name: 'Contacts' });
    expect(list).toHaveAttribute('data-testid', 'stack');
    expect(
      within(list)
        .getAllByRole('img')
        .map(avatar => avatar.getAttribute('aria-label'))
    ).toEqual(['Sam Taylor', 'Alex Chen']);
  });

  it('folds people beyond three into a +N naming them in its noun', () => {
    renderStack([SAM, ALEX, PRIYA, JORDAN, KIM]);

    expect(screen.getAllByRole('img')).toHaveLength(3);
    expect(screen.getByText('+2')).toHaveAccessibleName(
      '2 more contacts: Jordan Lee, Kim Nguyen'
    );
  });

  it('words one hidden person in the singular', () => {
    renderStack([SAM, ALEX, PRIYA, JORDAN]);

    expect(screen.getByText('+1')).toHaveAccessibleName(
      '1 more contact: Jordan Lee'
    );
  });

  it('shows a person’s photo when they have one', async () => {
    renderStack([
      { id: 1, name: 'Sam Taylor', photoUrl: 'https://x.test/sam.jpg' },
    ]);

    expect(await screen.findByAltText('Sam Taylor')).toHaveAttribute(
      'src',
      'https://x.test/sam.jpg'
    );
  });
});
