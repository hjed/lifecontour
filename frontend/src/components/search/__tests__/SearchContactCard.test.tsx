/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { SearchContactCard } from '../SearchContactCard';
import { DisplayContact } from '@/hooks/useDisplayContacts';
import { ContactRankingSignals } from '@/utils/searchUtils';

// Mock next/link
jest.mock('next/link', () => {
  return function MockLink({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) {
    return <a href={href}>{children}</a>;
  };
});

// Mock FavouriteToggle
jest.mock('@/components/contacts/FavouriteToggle', () => ({
  FavouriteToggle: ({
    contactName,
    isFavourite,
  }: {
    contactId: string;
    contactName: string;
    isFavourite: boolean;
  }) => (
    <button
      aria-label={`${isFavourite ? 'Remove' : 'Add'} ${contactName} as favourite`}
    >
      ★
    </button>
  ),
}));

const baseContact: DisplayContact = {
  id: '1',
  name: 'Alice Smith',
  is_favourite: false,
  primary_email: 'alice@example.com',
  primary_phone: '+61400000000',
  tags: [],
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-06-01T00:00:00Z',
};

const defaultSignals: ContactRankingSignals = {
  isFavourite: false,
  hasSummary: false,
  journalCount30d: 0,
  activityCount30d: 0,
  lastActivityDate: null,
  relationships: [],
};

describe('SearchContactCard', () => {
  it('renders contact name as a link', () => {
    render(
      <SearchContactCard contact={baseContact} signals={defaultSignals} />
    );

    const link = screen.getByRole('link', { name: /alice smith/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/contacts/1');
  });

  it('renders favourite badge when isFavourite is true', () => {
    const signals: ContactRankingSignals = {
      ...defaultSignals,
      isFavourite: true,
    };

    render(<SearchContactCard contact={baseContact} signals={signals} />);

    expect(screen.getByLabelText('Favourite contact')).toBeInTheDocument();
  });

  it('does not render favourite badge when isFavourite is false', () => {
    render(
      <SearchContactCard contact={baseContact} signals={defaultSignals} />
    );

    expect(
      screen.queryByLabelText('Favourite contact')
    ).not.toBeInTheDocument();
  });

  it('renders journal count badge when journalCount30d > 0', () => {
    const signals: ContactRankingSignals = {
      ...defaultSignals,
      journalCount30d: 5,
    };

    render(<SearchContactCard contact={baseContact} signals={signals} />);

    expect(
      screen.getByLabelText('5 journal entries in last 30 days')
    ).toBeInTheDocument();
  });

  it('does not render journal count badge when journalCount30d is 0', () => {
    render(
      <SearchContactCard contact={baseContact} signals={defaultSignals} />
    );

    expect(
      screen.queryByLabelText(/journal entries in last 30 days/i)
    ).not.toBeInTheDocument();
  });

  it('renders activity indicator when activityCount30d > 0', () => {
    const signals: ContactRankingSignals = {
      ...defaultSignals,
      activityCount30d: 8,
    };

    render(<SearchContactCard contact={baseContact} signals={signals} />);

    expect(screen.getByLabelText('8 recent activities')).toBeInTheDocument();
  });

  it('does not render activity indicator when activityCount30d is 0', () => {
    render(
      <SearchContactCard contact={baseContact} signals={defaultSignals} />
    );

    expect(
      screen.queryByLabelText(/recent activities/i)
    ).not.toBeInTheDocument();
  });

  it('renders AI summary indicator when hasSummary is true', () => {
    const signals: ContactRankingSignals = {
      ...defaultSignals,
      hasSummary: true,
    };

    render(<SearchContactCard contact={baseContact} signals={signals} />);

    expect(screen.getByLabelText('AI summary available')).toBeInTheDocument();
  });

  it('does not render AI summary indicator when hasSummary is false', () => {
    render(
      <SearchContactCard contact={baseContact} signals={defaultSignals} />
    );

    expect(
      screen.queryByLabelText('AI summary available')
    ).not.toBeInTheDocument();
  });

  it('renders email and phone from contact data', () => {
    render(
      <SearchContactCard contact={baseContact} signals={defaultSignals} />
    );

    expect(screen.getByText('alice@example.com')).toBeInTheDocument();
    expect(screen.getByText('+61400000000')).toBeInTheDocument();
  });

  it('renders all ranking badges together', () => {
    const signals: ContactRankingSignals = {
      isFavourite: true,
      hasSummary: true,
      journalCount30d: 3,
      activityCount30d: 7,
      lastActivityDate: '2024-06-10T00:00:00Z',
      relationships: ['Parent of Bob'],
    };

    render(<SearchContactCard contact={baseContact} signals={signals} />);

    expect(screen.getByLabelText('Favourite contact')).toBeInTheDocument();
    expect(screen.getByLabelText('AI summary available')).toBeInTheDocument();
    expect(
      screen.getByLabelText('3 journal entries in last 30 days')
    ).toBeInTheDocument();
    expect(screen.getByLabelText('7 recent activities')).toBeInTheDocument();
  });
});
