/** @jest-environment jsdom */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CalendarSettingsDialog } from '../CalendarSettingsDialog';
import { useCreateCalendar, useUpdateCalendar } from '@/lib/api/journals';

// Mock the API hooks
jest.mock('@/lib/api/journals', () => ({
  useCreateCalendar: jest.fn(),
  useUpdateCalendar: jest.fn(),
}));

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
});
