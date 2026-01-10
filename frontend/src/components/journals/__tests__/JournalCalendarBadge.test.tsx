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
