/**
 * @jest-environment jsdom
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CalendarSettings } from '../CalendarSettings';
import { useCalendars, useDeleteCalendar } from '@/lib/api/journals';

jest.mock('@/lib/api/journals', () => ({
  useCalendars: jest.fn(),
  useDeleteCalendar: jest.fn(),
}));

jest.mock('../CalendarSettingsDialog', () => ({
  CalendarSettingsDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid='calendar-settings-dialog' /> : null,
}));

describe('CalendarSettings', () => {
  const mockDeleteCalendar = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();

    (useCalendars as jest.Mock).mockReturnValue({
      data: {
        data: [
          {
            id: '1',
            attributes: {
              name: 'Work',
              color: '#ff0000',
              description: 'Work calendar',
              is_synced_to_google: false,
              google_calendar_id: null,
            },
          },
        ],
      },
      isLoading: false,
      error: null,
    });

    (useDeleteCalendar as jest.Mock).mockReturnValue({
      mutateAsync: mockDeleteCalendar,
      isPending: false,
    });

    mockDeleteCalendar.mockResolvedValue(undefined);
  });

  it('opens a delete confirmation dialog and does not delete on cancel', async () => {
    render(<CalendarSettings />);

    fireEvent.click(
      screen.getByRole('button', { name: 'Delete calendar Work' })
    );

    expect(
      screen.getByRole('heading', { name: 'Delete Calendar' })
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => {
      expect(mockDeleteCalendar).not.toHaveBeenCalled();
    });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('deletes the selected calendar when confirmed', async () => {
    render(<CalendarSettings />);

    fireEvent.click(
      screen.getByRole('button', { name: 'Delete calendar Work' })
    );

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(mockDeleteCalendar).toHaveBeenCalledWith('1');
    });
  });
});
