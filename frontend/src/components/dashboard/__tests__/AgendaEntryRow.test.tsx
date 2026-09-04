/**
 * @jest-environment jsdom
 *
 * One agenda entry as the card draws it (**W12**–**W18**).
 *
 * The row is a pure function of the payload entry, so every element is tested
 * from a fixture rather than through the query: which element appears, what it
 * says, where it links, and how a cancelled entry is kept from reading as
 * still happening.
 */

import { render, screen, within } from '@testing-library/react';
import { AgendaEntryRow } from '../AgendaEntryRow';
import type { HomeDashboardAgendaEntry } from '@/lib/api/home-dashboard';

const COFFEE: HomeDashboardAgendaEntry = {
  journal_id: 42,
  title: 'Coffee with Sam',
  is_all_day: false,
  starts_at: '2026-07-31T09:00:00+10:00',
  ends_at: '2026-07-31T10:00:00+10:00',
  start_time: '09:00:00',
  end_time: '10:00:00',
  timezone: 'Australia/Sydney',
  location: 'The good place',
  calendar_color: '#336699',
  is_cancelled: false,
  tags: [
    { id: 'tag-1', name: 'social', color: '#ff0000' },
    { id: 'tag-2', name: 'work', color: null },
  ],
  participants: [
    { contact_id: 7, name: 'Sam Taylor' },
    { contact_id: 8, name: 'Alex Chen' },
  ],
};

const HOLIDAY: HomeDashboardAgendaEntry = {
  journal_id: 43,
  title: 'Public holiday',
  is_all_day: true,
  starts_at: '2026-07-31T00:00:00+10:00',
  ends_at: '2026-07-31T00:00:00+10:00',
  start_time: null,
  end_time: null,
  timezone: 'Australia/Sydney',
  location: null,
  calendar_color: null,
  is_cancelled: false,
  tags: [],
  participants: [],
};

function renderRow(entry: HomeDashboardAgendaEntry) {
  return render(
    <ul>
      <AgendaEntryRow entry={entry} />
    </ul>
  );
}

function row() {
  return screen.getByRole('listitem');
}

describe('AgendaEntryRow', () => {
  describe('the title (W14)', () => {
    it('links the journal title to the journal', () => {
      renderRow(COFFEE);

      const link = screen.getByRole('link', { name: 'Coffee with Sam' });
      expect(link).toHaveAttribute('href', '/journals/42');
    });
  });

  describe('a timed entry (W13)', () => {
    it('shows the clock range in tabular figures with its location', () => {
      renderRow(COFFEE);

      const time = screen.getByTestId('agenda-entry-time');
      expect(time).toHaveTextContent('09:00 – 10:00');
      expect(time).toHaveClass('tabular-nums');
      expect(screen.getByTestId('agenda-entry-location')).toHaveTextContent(
        'The good place'
      );
      expect(screen.queryByText('All day')).not.toBeInTheDocument();
    });

    it('omits the location separator when there is no location', () => {
      renderRow({ ...COFFEE, location: null });

      expect(screen.getByTestId('agenda-entry-time')).toHaveTextContent(
        '09:00 – 10:00'
      );
      expect(
        screen.queryByTestId('agenda-entry-location')
      ).not.toBeInTheDocument();
      expect(row()).not.toHaveTextContent('·');
    });

    it('shows the start alone when the payload has no end time', () => {
      renderRow({ ...COFFEE, end_time: null });

      expect(screen.getByTestId('agenda-entry-time')).toHaveTextContent(
        /^09:00$/
      );
    });
  });

  describe('an all-day entry (W12)', () => {
    it('carries the ALL DAY marker in place of a time', () => {
      renderRow(HOLIDAY);

      expect(screen.getByTestId('agenda-entry-all-day')).toHaveTextContent(
        /all day/i
      );
      expect(screen.queryByTestId('agenda-entry-time')).not.toBeInTheDocument();
    });

    it('still shows a location when the all-day entry has one', () => {
      renderRow({ ...HOLIDAY, location: 'Home' });

      expect(screen.getByTestId('agenda-entry-location')).toHaveTextContent(
        'Home'
      );
    });
  });

  describe('tags (W15)', () => {
    it('draws one outline badge per tag in the tag colour', () => {
      renderRow(COFFEE);

      const tags = within(screen.getByTestId('agenda-entry-tags')).getAllByText(
        /social|work/
      );
      expect(tags.map(tag => tag.textContent)).toEqual(['social', 'work']);
      expect(tags[0]).toHaveStyle({ borderColor: '#ff0000', color: '#ff0000' });
    });

    it('draws no tag row when the entry has no tags', () => {
      renderRow(HOLIDAY);

      expect(screen.queryByTestId('agenda-entry-tags')).not.toBeInTheDocument();
    });
  });

  describe('participants (W16)', () => {
    it('renders the avatar stack when there is anyone', () => {
      renderRow(COFFEE);

      const stack = screen.getByRole('group', { name: 'Participants' });
      expect(within(stack).getAllByRole('img')).toHaveLength(2);
    });

    it('renders no stack when there is nobody', () => {
      renderRow(HOLIDAY);

      expect(screen.queryByRole('group')).not.toBeInTheDocument();
    });
  });

  describe('the accent bar (W17)', () => {
    it('takes the calendar colour', () => {
      renderRow(COFFEE);

      const accent = screen.getByTestId('agenda-entry-accent');
      expect(accent).toHaveStyle({ backgroundColor: '#336699' });
      expect(accent).toHaveAttribute('aria-hidden', 'true');
    });

    it('falls back to the section colour when the calendar has none', () => {
      renderRow(HOLIDAY);

      const accent = screen.getByTestId('agenda-entry-accent');
      expect(accent).not.toHaveAttribute('style');
      expect(accent).toHaveClass('bg-chart-1');
    });
  });

  describe('a cancelled entry (W18)', () => {
    const CANCELLED = { ...COFFEE, is_cancelled: true };

    it('is badged CANCELLED beside the title', () => {
      renderRow(CANCELLED);

      expect(screen.getByTestId('agenda-entry-cancelled')).toHaveTextContent(
        /cancelled/i
      );
    });

    it('strikes the title through and mutes the whole row', () => {
      renderRow(CANCELLED);

      expect(screen.getByRole('link', { name: 'Coffee with Sam' })).toHaveClass(
        'line-through'
      );
      expect(row()).toHaveClass('opacity-60');
    });

    it('mutes the accent bar rather than drawing the calendar colour', () => {
      renderRow(CANCELLED);

      const accent = screen.getByTestId('agenda-entry-accent');
      expect(accent).not.toHaveAttribute('style');
      expect(accent).not.toHaveClass('bg-chart-1');
    });

    it('is not badged when the entry is not cancelled', () => {
      renderRow(COFFEE);

      expect(
        screen.queryByTestId('agenda-entry-cancelled')
      ).not.toBeInTheDocument();
      expect(row()).not.toHaveClass('opacity-60');
    });
  });

  it('marks every icon as decorative', () => {
    const { container } = renderRow(COFFEE);

    const icons = container.querySelectorAll('svg');
    expect(icons.length).toBeGreaterThan(0);
    icons.forEach(icon => {
      expect(icon).toHaveAttribute('aria-hidden', 'true');
    });
  });

  it('identifies the row by its journal for the tests that need one row', () => {
    renderRow(COFFEE);

    expect(screen.getByTestId('agenda-entry-42')).toBe(row());
  });
});
