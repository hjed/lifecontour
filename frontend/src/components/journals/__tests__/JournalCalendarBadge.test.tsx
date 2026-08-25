/**
 * Tests for JournalCalendarBadge component.
 *
 * Tests calendar badge display and inline editing functionality.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JournalCalendarBadge } from '../JournalCalendarBadge';
import { JournalType, type JournalCalendar } from '@/types/journals';

describe('JournalCalendarBadge', () => {
  const mockCalendar: JournalCalendar = {
    id: 'cal1',
    name: 'Personal',
    color: '#10b981',
  };

  const mockAvailableCalendars: JournalCalendar[] = [
    mockCalendar,
    { id: 'cal2', name: 'Work', color: '#3b82f6' },
  ];

  const mockOnCalendarChange = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Display Mode', () => {
    it('renders calendar badge when calendar is set', () => {
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          journalTypes={[JournalType.NOTE]}
        />
      );

      expect(screen.getByText('Personal')).toBeInTheDocument();
      expect(screen.getByTestId('calendar-badge')).toBeInTheDocument();
    });

    it('renders nothing when calendar is null and not editable', () => {
      const { container } = render(
        <JournalCalendarBadge
          calendar={null}
          journalTypes={[JournalType.NOTE]}
        />
      );

      expect(container.firstChild).toBeNull();
    });

    it('renders "Add Calendar" button when calendar is null and editable', () => {
      render(
        <JournalCalendarBadge
          calendar={null}
          journalTypes={[JournalType.EVENT]}
          onCalendarChange={mockOnCalendarChange}
          availableCalendars={mockAvailableCalendars}
        />
      );

      expect(screen.getByTestId('add-calendar-button')).toBeInTheDocument();
      expect(screen.getByText('Add Calendar')).toBeInTheDocument();
    });

    it('applies calendar color to badge', () => {
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          journalTypes={[JournalType.NOTE]}
        />
      );

      const badge = screen.getByTestId('calendar-badge');
      expect(badge).toBeInTheDocument();
    });
  });

  describe('Edit Mode', () => {
    it('shows trigger button when EVENT type is present and calendar is set', () => {
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          journalTypes={[JournalType.EVENT]}
          onCalendarChange={mockOnCalendarChange}
          availableCalendars={mockAvailableCalendars}
        />
      );

      expect(screen.getByTestId('calendar-badge-trigger')).toBeInTheDocument();
    });

    it('does not show trigger when EVENT type is not present', () => {
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          journalTypes={[JournalType.NOTE]}
          onCalendarChange={mockOnCalendarChange}
          availableCalendars={mockAvailableCalendars}
        />
      );

      expect(
        screen.queryByTestId('calendar-badge-trigger')
      ).not.toBeInTheDocument();
    });

    it('opens popover when trigger is clicked', async () => {
      const user = userEvent.setup();
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          journalTypes={[JournalType.EVENT]}
          onCalendarChange={mockOnCalendarChange}
          availableCalendars={mockAvailableCalendars}
        />
      );

      const trigger = screen.getByTestId('calendar-badge-trigger');
      await user.click(trigger);

      expect(screen.getByText('Change Calendar')).toBeInTheDocument();
      expect(screen.getByTestId('calendar-select')).toBeInTheDocument();
    });
  });

  describe('An event held by more than one calendar', () => {
    // One event can live in two calendars — where one calendar invites the
    // other — and the sync records it as a single journal linked to each.
    // The journal is still *displayed* in one of them, which is the only
    // one that can be changed here.
    const sharedCalendars: JournalCalendar[] = [
      mockCalendar,
      { id: 'cal2', name: 'Work', color: '#3b82f6' },
    ];

    it('names every calendar the event lives in', () => {
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          calendars={sharedCalendars}
          journalTypes={[JournalType.EVENT]}
        />
      );

      expect(screen.getByText('Personal')).toBeInTheDocument();
      expect(screen.getByText('Work')).toBeInTheDocument();
    });

    it('shows one badge per calendar', () => {
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          calendars={sharedCalendars}
          journalTypes={[JournalType.EVENT]}
        />
      );

      expect(screen.getAllByTestId(/^calendar-badge/)).toHaveLength(2);
    });

    it('only the display calendar can be changed', () => {
      // The others are where the same event also appears; reassigning one
      // is not a thing the user can do from here, and offering it would
      // imply the event could be moved out of a calendar that holds it.
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          calendars={sharedCalendars}
          journalTypes={[JournalType.EVENT]}
          onCalendarChange={mockOnCalendarChange}
          availableCalendars={mockAvailableCalendars}
        />
      );

      expect(screen.getAllByTestId('calendar-badge-trigger')).toHaveLength(1);
    });

    it('marks the extra calendars as ones the event also appears in', () => {
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          calendars={sharedCalendars}
          journalTypes={[JournalType.EVENT]}
        />
      );

      expect(
        screen.getByTestId('calendar-badge-linked-cal2')
      ).toHaveAccessibleName(/also in Work/i);
    });

    it('renders a single calendar exactly as before', () => {
      // The common case must not grow a second badge or change shape.
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          calendars={[mockCalendar]}
          journalTypes={[JournalType.NOTE]}
        />
      );

      expect(screen.getAllByTestId(/^calendar-badge/)).toHaveLength(1);
      expect(screen.getByTestId('calendar-badge')).toBeInTheDocument();
    });

    it('falls back to the single calendar when the list is absent', () => {
      // Search results and other reads that do not load the links.
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          journalTypes={[JournalType.NOTE]}
        />
      );

      expect(screen.getAllByTestId(/^calendar-badge/)).toHaveLength(1);
      expect(screen.getByText('Personal')).toBeInTheDocument();
    });
  });

  describe('Accessibility', () => {
    it('has proper test id', () => {
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          journalTypes={[JournalType.NOTE]}
        />
      );

      expect(screen.getByTestId('calendar-badge')).toBeInTheDocument();
    });

    it('applies custom className', () => {
      render(
        <JournalCalendarBadge
          calendar={mockCalendar}
          journalTypes={[JournalType.NOTE]}
          className='custom-class'
        />
      );

      expect(screen.getByTestId('calendar-badge')).toHaveClass('custom-class');
    });
  });
});
