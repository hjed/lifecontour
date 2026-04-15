/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ImportantDatesList } from '../ImportantDatesList';
import {
  ContactAttributes,
  ImportantDatePrecision,
  ImportantDateTypeEnum,
} from '@/types/contacts';
import * as contactsApi from '@/lib/api/contacts';

// Mock the API functions
jest.mock('@/lib/api/contacts', () => ({
  useUpdateContact: jest.fn(),
}));

jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const mockContactAttributes: ContactAttributes = {
  first_name: 'John',
  created_at: '2023-01-01T00:00:00Z',
  updated_at: '2023-01-01T00:00:00Z',
  contact_methods: [],
  addresses: [],
  notes: [],
  relationships: [],
  important_dates: [
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
  ],
};

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

describe('ImportantDatesList', () => {
  const mockUpdateContact = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();

    (contactsApi.useUpdateContact as jest.Mock).mockReturnValue({
      mutateAsync: mockUpdateContact,
      isPending: false,
    });
  });

  it('renders important dates list with formatted dates', () => {
    render(
      <ImportantDatesList
        contactId='123'
        contactAttributes={mockContactAttributes}
      />,
      {
        wrapper: createWrapper(),
      }
    );

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
    render(
      <ImportantDatesList
        contactId='123'
        contactAttributes={{ ...mockContactAttributes, important_dates: [] }}
      />,
      {
        wrapper: createWrapper(),
      }
    );

    expect(
      screen.getByText('No important dates yet. Click the + button to add one.')
    ).toBeInTheDocument();
  });

  it('shows add button', () => {
    render(
      <ImportantDatesList
        contactId='123'
        contactAttributes={mockContactAttributes}
      />,
      {
        wrapper: createWrapper(),
      }
    );

    const addButton = screen.getByLabelText('Add important date');
    expect(addButton).toBeInTheDocument();
  });

  it('shows delete buttons for each date', () => {
    render(
      <ImportantDatesList
        contactId='123'
        contactAttributes={mockContactAttributes}
      />,
      {
        wrapper: createWrapper(),
      }
    );

    const deleteButtons = screen.getAllByLabelText(/Delete/);
    expect(deleteButtons).toHaveLength(2);
  });

  it('calls updateContact with item removed when delete button clicked and confirmed', async () => {
    render(
      <ImportantDatesList
        contactId='123'
        contactAttributes={mockContactAttributes}
      />,
      {
        wrapper: createWrapper(),
      }
    );

    // Click first delete button
    const deleteButton = screen.getByLabelText('Delete birthday');
    fireEvent.click(deleteButton);

    // Wait for the dialog to appear and click the confirm button
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    const confirmButton = screen.getByRole('button', { name: 'Delete' });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      // The update payload should now have only 1 item (the remaining marriage anniversary)
      expect(mockUpdateContact).toHaveBeenCalled();

      const updateData = mockUpdateContact.mock.calls[0][0];
      expect(updateData.id).toBe('123');
      expect(updateData.data.important_dates).toHaveLength(1);
      expect(updateData.data.important_dates[0].id).toBe('2');
    });
  });
});
