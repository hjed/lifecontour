/** @jest-environment jsdom */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CalendarSettingsDialog } from '../CalendarSettingsDialog';
import { useCreateCalendar, useUpdateCalendar } from '@/lib/api/journals';
import { useGoogleCalendars, useGoogleStatus } from '@/lib/api/integrations';

// Mock the API hooks
jest.mock('@/lib/api/journals', () => ({
  useCreateCalendar: jest.fn(),
  useUpdateCalendar: jest.fn(),
}));

jest.mock('@/lib/api/integrations', () => ({
  useGoogleCalendars: jest.fn(),
  useGoogleStatus: jest.fn(),
}));

// Default Google status: connected with calendar scopes
const mockGoogleConnected = {
  data: {
    data: {
      attributes: {
        connected: true,
        needsReconsent: false,
      },
    },
  },
};

const mockGoogleDisconnected = {
  data: {
    data: {
      attributes: {
        connected: false,
        needsReconsent: false,
      },
    },
  },
};

const mockGoogleCalendars = {
  data: {
    data: [
      {
        id: 'primary@gmail.com',
        type: 'google-calendar',
        attributes: {
          summary: 'My Calendar',
          primary: true,
          accessRole: 'owner',
        },
      },
      {
        id: 'work@group.v.calendar.google.com',
        type: 'google-calendar',
        attributes: {
          summary: 'Work Calendar',
          primary: false,
          accessRole: 'writer',
        },
      },
      {
        id: 'shared@example.com',
        type: 'google-calendar',
        attributes: {
          summary: 'Shared Calendar',
          primary: false,
          accessRole: 'reader',
        },
      },
      {
        id: 'busy@example.com',
        type: 'google-calendar',
        attributes: {
          summary: 'Busy Calendar',
          primary: false,
          accessRole: 'freeBusyReader',
        },
      },
    ],
  },
  isLoading: false,
};

describe('CalendarSettingsDialog', () => {
  const mockCreate = jest.fn();
  const mockUpdate = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    (useCreateCalendar as jest.Mock).mockReturnValue({
      mutateAsync: mockCreate,
      isPending: false,
    });
    (useUpdateCalendar as jest.Mock).mockReturnValue({
      mutateAsync: mockUpdate,
      isPending: false,
    });
    (useGoogleStatus as jest.Mock).mockReturnValue(mockGoogleConnected);
    (useGoogleCalendars as jest.Mock).mockReturnValue(mockGoogleCalendars);
  });

  it('renders create form when no calendar is provided', () => {
    render(<CalendarSettingsDialog open={true} onOpenChange={jest.fn()} />);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Create Calendar')).toBeInTheDocument();
    expect(screen.getByLabelText(/name/i)).toHaveValue('');
    expect(screen.getByLabelText(/^color$/i)).toHaveValue('#3b82f6');
    expect(screen.getByLabelText(/color picker/i)).toHaveValue('#3b82f6');
  });

  it('renders edit form when calendar is provided', () => {
    const calendar = {
      id: '1',
      name: 'Work',
      color: '#ff0000',
      description: 'Work stuff',
    };
    render(
      <CalendarSettingsDialog
        open={true}
        onOpenChange={jest.fn()}
        calendar={calendar}
      />
    );

    expect(screen.getByText('Edit Calendar')).toBeInTheDocument();
    expect(screen.getByLabelText(/name/i)).toHaveValue('Work');
    expect(screen.getByLabelText(/description/i)).toHaveValue('Work stuff');
    expect(screen.getByLabelText(/^color$/i)).toHaveValue('#ff0000');
    expect(screen.getByLabelText(/color picker/i)).toHaveValue('#ff0000');
  });

  it('calls createCalendar on submit when creating', async () => {
    const onOpenChange = jest.fn();
    render(<CalendarSettingsDialog open={true} onOpenChange={onOpenChange} />);

    fireEvent.change(screen.getByLabelText(/name/i), {
      target: { value: 'Personal' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'Personal',
          color: '#3b82f6',
        })
      );
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it('calls updateCalendar on submit when editing', async () => {
    const onOpenChange = jest.fn();
    const calendar = { id: '1', name: 'Work', color: '#ff0000' };
    render(
      <CalendarSettingsDialog
        open={true}
        onOpenChange={onOpenChange}
        calendar={calendar}
      />
    );

    fireEvent.change(screen.getByLabelText(/name/i), {
      target: { value: 'Work Updated' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith({
        id: '1',
        data: expect.objectContaining({
          name: 'Work Updated',
          color: '#ff0000',
        }),
      });
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it('enables Google sync toggle when Google is connected with calendar scopes', () => {
    render(<CalendarSettingsDialog open={true} onOpenChange={jest.fn()} />);

    const toggle = screen.getByTestId('google-sync-toggle');
    expect(toggle).not.toBeDisabled();
  });

  it('disables Google sync toggle when Google is not connected', () => {
    (useGoogleStatus as jest.Mock).mockReturnValue(mockGoogleDisconnected);

    render(<CalendarSettingsDialog open={true} onOpenChange={jest.fn()} />);

    const toggle = screen.getByTestId('google-sync-toggle');
    expect(toggle).toBeDisabled();
  });

  it('disables Google sync toggle when needsReconsent is true', () => {
    (useGoogleStatus as jest.Mock).mockReturnValue({
      data: {
        data: {
          attributes: {
            connected: true,
            needsReconsent: true,
          },
        },
      },
    });

    render(<CalendarSettingsDialog open={true} onOpenChange={jest.fn()} />);

    const toggle = screen.getByTestId('google-sync-toggle');
    expect(toggle).toBeDisabled();
  });
  describe('read-only Google calendars', () => {
    /**
     * A calendar shared read-only syncs in but never out: Google refuses
     * every write. Nothing else in the product says so, so the moment of
     * choosing it is the only place the user can learn it.
     */
    const selectGoogleCalendar = async (name: RegExp) => {
      fireEvent.click(screen.getByTestId('google-sync-toggle'));
      fireEvent.click(await screen.findByTestId('google-calendar-select'));
      fireEvent.click(await screen.findByRole('option', { name }));
    };

    it('warns that a read-only calendar will not receive changes', async () => {
      render(<CalendarSettingsDialog open={true} onOpenChange={jest.fn()} />);

      await selectGoogleCalendar(/Shared Calendar/);

      const warning = await screen.findByTestId('read-only-calendar-warning');
      expect(warning).toHaveTextContent(/read-only access/i);
      // The outbound half is the part that surprises people, so it is the
      // part the warning must state outright.
      expect(warning).toHaveTextContent(/not sent back to Google/i);
    });

    it('does not promise full event detail it cannot guarantee', async () => {
      /**
       * `freeBusyReader` shares availability only, so events arrive without
       * their details. One message covers both read-only roles, which means
       * it must not claim more than the weaker one delivers.
       */
      render(<CalendarSettingsDialog open={true} onOpenChange={jest.fn()} />);

      await selectGoogleCalendar(/Busy Calendar/);

      const warning = await screen.findByTestId('read-only-calendar-warning');
      expect(warning).toHaveTextContent(/whatever detail Google shares/i);
    });

    it('does not warn about a calendar the account can write to', async () => {
      render(<CalendarSettingsDialog open={true} onOpenChange={jest.fn()} />);

      await selectGoogleCalendar(/Work Calendar/);

      expect(
        screen.queryByTestId('read-only-calendar-warning')
      ).not.toBeInTheDocument();
    });

    it('marks read-only calendars in the list before one is chosen', async () => {
      render(<CalendarSettingsDialog open={true} onOpenChange={jest.fn()} />);

      fireEvent.click(screen.getByTestId('google-sync-toggle'));
      fireEvent.click(await screen.findByTestId('google-calendar-select'));

      expect(
        await screen.findByRole('option', {
          name: /Shared Calendar \(read-only\)/,
        })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('option', { name: /^Work Calendar$/ })
      ).toBeInTheDocument();
    });

    it('drops the warning when Google sync is turned back off', async () => {
      render(<CalendarSettingsDialog open={true} onOpenChange={jest.fn()} />);

      await selectGoogleCalendar(/Shared Calendar/);
      expect(
        await screen.findByTestId('read-only-calendar-warning')
      ).toBeInTheDocument();

      fireEvent.click(screen.getByTestId('google-sync-toggle'));

      await waitFor(() => {
        expect(
          screen.queryByTestId('read-only-calendar-warning')
        ).not.toBeInTheDocument();
      });
    });
  });
});
