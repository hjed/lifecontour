/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ImportantDatesList } from '../ImportantDatesList';
import {
  ImportantDatePrecision,
  ImportantDateResource,
  ImportantDateTypeEnum,
} from '@/types/contacts';
import * as contactsApi from '@/lib/api/contacts';

// Mock the API functions. The inline editor pulls custom date types from the
// same module, so those hooks have to be mocked too or it cannot render.
jest.mock('@/lib/api/contacts', () => ({
  useAddContactImportantDate: jest.fn(),
  useUpdateContactImportantDate: jest.fn(),
  useDeleteContactImportantDate: jest.fn(),
  useCustomDateTypes: jest.fn(),
  useCreateCustomDateType: jest.fn(),
}));

jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const mockDates: ImportantDateResource[] = [
  {
    id: '1',
    type: 'important_dates',
    attributes: {
      date_type: ImportantDateTypeEnum.BIRTHDAY,
      precision: ImportantDatePrecision.FULL,
      year: 1990,
      month: 5,
      day: 15,
    },
  },
  {
    id: '2',
    type: 'important_dates',
    attributes: {
      date_type: ImportantDateTypeEnum.ANNIVERSARY_MARRIAGE,
      precision: ImportantDatePrecision.YEAR,
      year: 2010,
    },
  },
];

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const TestWrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  TestWrapper.displayName = 'TestWrapper';
  return TestWrapper;
};

const renderList = (dates: ImportantDateResource[] = mockDates) =>
  render(<ImportantDatesList contactId='123' dates={dates} />, {
    wrapper: createWrapper(),
  });

describe('ImportantDatesList', () => {
  const mockAddDate = jest.fn();
  const mockUpdateDate = jest.fn();
  const mockDeleteDate = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();

    (contactsApi.useAddContactImportantDate as jest.Mock).mockReturnValue({
      mutateAsync: mockAddDate,
      isPending: false,
    });
    (contactsApi.useUpdateContactImportantDate as jest.Mock).mockReturnValue({
      mutateAsync: mockUpdateDate,
      isPending: false,
    });
    (contactsApi.useDeleteContactImportantDate as jest.Mock).mockReturnValue({
      mutateAsync: mockDeleteDate,
      isPending: false,
    });
    (contactsApi.useCustomDateTypes as jest.Mock).mockReturnValue({
      data: { data: [] },
    });
    (contactsApi.useCreateCustomDateType as jest.Mock).mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    });
  });

  it('renders important dates list with formatted dates', () => {
    renderList();

    expect(screen.getByText('Important Dates')).toBeInTheDocument();

    // Birthday should be visible and formatted
    expect(screen.getByText(/birthday/i)).toBeInTheDocument();
    // E.g. "15 May 1990" depending on exact formatting
    expect(screen.getByText(/1990/)).toBeInTheDocument();

    // Marriage anniversary
    expect(screen.getByText(/marriage anniversary/i)).toBeInTheDocument();
    expect(screen.getByText('2010')).toBeInTheDocument();
  });

  it('renders empty state when no dates', () => {
    renderList([]);

    expect(
      screen.getByText('No important dates yet. Click the + button to add one.')
    ).toBeInTheDocument();
  });

  it('shows add button', () => {
    renderList();

    expect(screen.getByLabelText('Add important date')).toBeInTheDocument();
  });

  it('shows edit and delete buttons for each date', () => {
    renderList();

    expect(screen.getAllByLabelText(/^Edit /)).toHaveLength(2);
    expect(screen.getAllByLabelText(/^Delete /)).toHaveLength(2);
  });

  it('opens the inline editor prefilled from the row being edited', () => {
    renderList();

    fireEvent.click(screen.getByLabelText('Edit birthday'));

    // The editor replaces that row, prefilled with its stored values.
    expect(screen.getByDisplayValue('1990')).toBeInTheDocument();
    expect(screen.getByDisplayValue('15')).toBeInTheDocument();
    expect(screen.getByDisplayValue('5')).toBeInTheDocument();

    // The other row is untouched and still shows its own value.
    expect(screen.getByText('2010')).toBeInTheDocument();
  });

  it('edits only one row at a time', () => {
    renderList();

    fireEvent.click(screen.getByLabelText('Edit birthday'));
    expect(screen.getAllByLabelText('Save date')).toHaveLength(1);

    fireEvent.click(screen.getByLabelText('Edit marriage_anniversary'));
    expect(screen.getAllByLabelText('Save date')).toHaveLength(1);
    expect(screen.getByDisplayValue('2010')).toBeInTheDocument();
  });

  it('saves an edit against the date being edited, not the whole contact', async () => {
    renderList();

    fireEvent.click(screen.getByLabelText('Edit birthday'));

    // Correct the birth year.
    fireEvent.change(screen.getByPlaceholderText('YYYY'), {
      target: { value: '1991' },
    });
    fireEvent.click(screen.getByLabelText('Save date'));

    await waitFor(() => {
      expect(mockUpdateDate).toHaveBeenCalledTimes(1);
    });
    expect(mockUpdateDate).toHaveBeenCalledWith({
      contactId: '123',
      dateId: '1',
      date: expect.objectContaining({
        date_type: ImportantDateTypeEnum.BIRTHDAY,
        precision: ImportantDatePrecision.FULL,
        year: 1991,
        month: 5,
        day: 15,
      }),
    });
  });

  it('closes the editor after a successful save', async () => {
    renderList();

    fireEvent.click(screen.getByLabelText('Edit birthday'));
    fireEvent.click(screen.getByLabelText('Save date'));

    await waitFor(() => {
      expect(screen.queryByLabelText('Save date')).not.toBeInTheDocument();
    });
  });

  it('leaves the editor open when the save fails', async () => {
    mockUpdateDate.mockRejectedValueOnce(new Error('Conflict'));
    renderList();

    fireEvent.click(screen.getByLabelText('Edit birthday'));
    fireEvent.click(screen.getByLabelText('Save date'));

    await waitFor(() => {
      expect(mockUpdateDate).toHaveBeenCalled();
    });
    // The user's in-progress edit must survive a rejected write.
    expect(screen.getByLabelText('Save date')).toBeInTheDocument();
  });

  it('restores the row when an edit is cancelled', () => {
    renderList();

    fireEvent.click(screen.getByLabelText('Edit birthday'));
    fireEvent.click(screen.getByLabelText('Cancel edit'));

    expect(screen.queryByLabelText('Save date')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Edit birthday')).toBeInTheDocument();
    expect(mockUpdateDate).not.toHaveBeenCalled();
  });

  it('adds a date through the add endpoint', async () => {
    renderList([]);

    fireEvent.click(screen.getByLabelText('Add important date'));
    fireEvent.change(screen.getByPlaceholderText('DD'), {
      target: { value: '1' },
    });
    fireEvent.change(screen.getByPlaceholderText('MM'), {
      target: { value: '6' },
    });
    fireEvent.change(screen.getByPlaceholderText('YYYY'), {
      target: { value: '2001' },
    });
    fireEvent.click(screen.getByLabelText('Save date'));

    await waitFor(() => {
      expect(mockAddDate).toHaveBeenCalledTimes(1);
    });
    expect(mockAddDate).toHaveBeenCalledWith({
      contactId: '123',
      date: expect.objectContaining({ year: 2001, month: 6, day: 1 }),
    });
  });

  it('deletes only the confirmed date, by id', async () => {
    renderList();

    fireEvent.click(screen.getByLabelText('Delete birthday'));

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(mockDeleteDate).toHaveBeenCalledWith({
        contactId: '123',
        dateId: '1',
      });
    });
  });
});
