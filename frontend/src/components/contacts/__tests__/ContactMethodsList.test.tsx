/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ContactMethodsList } from '../ContactMethodsList';
import { ContactMethodResource, ContactMethodType } from '@/types/contacts';
import * as contactsApi from '@/lib/api/contacts';

// Mock the API functions
jest.mock('@/lib/api/contacts', () => ({
  useAddContactMethod: jest.fn(),
  useDeleteContactMethod: jest.fn(),
  useSetContactValueArchived: jest.fn(),
  updateContactMethodField: jest.fn(),
}));

// Mock toast
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const mockMethods: readonly ContactMethodResource[] = [
  {
    id: '1',
    type: 'contact_methods',
    attributes: {
      method_type: ContactMethodType.EMAIL,
      value: 'john@example.com',
      label: 'Work',
      is_primary: true,
    },
  },
  {
    id: '2',
    type: 'contact_methods',
    attributes: {
      method_type: ContactMethodType.PHONE,
      value: '+61-2-1234-5678',
      label: 'Mobile',
      is_primary: false,
    },
  },
] as const;

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

describe('ContactMethodsList', () => {
  const mockAddMethod = jest.fn();
  const mockDeleteMethod = jest.fn();
  const mockUpdateField = jest.fn();
  const mockSetArchived = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();

    (contactsApi.useSetContactValueArchived as jest.Mock).mockReturnValue({
      mutateAsync: mockSetArchived,
      isPending: false,
    });

    (contactsApi.useAddContactMethod as jest.Mock).mockReturnValue({
      mutateAsync: mockAddMethod,
      isPending: false,
    });

    (contactsApi.useDeleteContactMethod as jest.Mock).mockReturnValue({
      mutateAsync: mockDeleteMethod,
      isPending: false,
    });

    (contactsApi.updateContactMethodField as jest.Mock).mockImplementation(
      mockUpdateField
    );
  });

  it('renders contact methods list with methods', () => {
    render(<ContactMethodsList contactId='123' methods={mockMethods} />, {
      wrapper: createWrapper(),
    });

    expect(screen.getByText('Contact Methods')).toBeInTheDocument();
    expect(screen.getByText('john@example.com')).toBeInTheDocument();
    expect(screen.getByText('+61 2 1234 5678')).toBeInTheDocument();
  });

  it('renders empty state when no methods', () => {
    render(<ContactMethodsList contactId='123' methods={[]} />, {
      wrapper: createWrapper(),
    });

    expect(
      screen.getByText('No contact methods yet. Click the + button to add one.')
    ).toBeInTheDocument();
  });

  it('shows add button', () => {
    render(<ContactMethodsList contactId='123' methods={mockMethods} />, {
      wrapper: createWrapper(),
    });

    const addButton = screen.getByLabelText('Add contact method');
    expect(addButton).toBeInTheDocument();
  });

  it('shows delete buttons for each method', () => {
    render(<ContactMethodsList contactId='123' methods={mockMethods} />, {
      wrapper: createWrapper(),
    });

    const deleteButtons = screen.getAllByLabelText(/Delete/);
    expect(deleteButtons).toHaveLength(2);
  });

  it('calls delete method when delete button clicked and confirmed', async () => {
    render(<ContactMethodsList contactId='123' methods={mockMethods} />, {
      wrapper: createWrapper(),
    });

    // Click the delete button to open the dialog
    const deleteButton = screen.getByLabelText('Delete email');
    fireEvent.click(deleteButton);

    // Wait for the dialog to appear and click the confirm button
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    const confirmButton = screen.getByRole('button', { name: 'Delete' });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(mockDeleteMethod).toHaveBeenCalledWith({
        contactId: '123',
        methodId: '1',
      });
    });
  });

  it('does not delete when user cancels confirmation', async () => {
    render(<ContactMethodsList contactId='123' methods={mockMethods} />, {
      wrapper: createWrapper(),
    });

    // Click the delete button to open the dialog
    const deleteButton = screen.getByLabelText('Delete email');
    fireEvent.click(deleteButton);

    // Wait for the dialog to appear and click the cancel button
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    const cancelButton = screen.getByRole('button', { name: 'Cancel' });
    fireEvent.click(cancelButton);

    await waitFor(() => {
      expect(mockDeleteMethod).not.toHaveBeenCalled();
    });
  });

  it('disables buttons when disabled prop is true', () => {
    render(
      <ContactMethodsList
        contactId='123'
        methods={mockMethods}
        disabled={true}
      />,
      { wrapper: createWrapper() }
    );

    const addButton = screen.getByLabelText('Add contact method');
    const deleteButtons = screen.getAllByLabelText(/Delete/);

    expect(addButton).toBeDisabled();
    deleteButtons.forEach(button => {
      expect(button).toBeDisabled();
    });
  });

  describe('archived methods', () => {
    const withArchived: readonly ContactMethodResource[] = [
      ...mockMethods,
      {
        id: '3',
        type: 'contact_methods',
        attributes: {
          method_type: ContactMethodType.EMAIL,
          value: 'old@example.com',
          label: 'School',
          is_primary: false,
          is_archived: true,
        },
      },
    ];

    it('keeps archived methods behind a collapsed section', () => {
      render(<ContactMethodsList contactId='123' methods={withArchived} />, {
        wrapper: createWrapper(),
      });

      const trigger = screen.getByRole('button', {
        name: 'Archived contact methods (1)',
      });
      expect(trigger).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByText('old@example.com')).not.toBeInTheDocument();

      fireEvent.click(trigger);

      expect(trigger).toHaveAttribute('aria-expanded', 'true');
      expect(screen.getByText('old@example.com')).toBeInTheDocument();
      expect(screen.getByText('School')).toBeInTheDocument();
    });

    it('has no archived section when nothing is archived', () => {
      render(<ContactMethodsList contactId='123' methods={mockMethods} />, {
        wrapper: createWrapper(),
      });

      expect(
        screen.queryByRole('button', { name: /Archived contact methods/ })
      ).not.toBeInTheDocument();
    });

    it('archives an active method', async () => {
      render(<ContactMethodsList contactId='123' methods={withArchived} />, {
        wrapper: createWrapper(),
      });

      fireEvent.click(
        screen.getByRole('button', { name: 'Archive john@example.com' })
      );

      await waitFor(() => {
        expect(mockSetArchived).toHaveBeenCalledWith({
          contactId: '123',
          kind: 'method',
          id: '1',
          archived: true,
        });
      });
    });

    it('restores an archived method', async () => {
      render(<ContactMethodsList contactId='123' methods={withArchived} />, {
        wrapper: createWrapper(),
      });

      fireEvent.click(
        screen.getByRole('button', { name: 'Archived contact methods (1)' })
      );
      fireEvent.click(
        screen.getByRole('button', { name: 'Restore old@example.com' })
      );

      await waitFor(() => {
        expect(mockSetArchived).toHaveBeenCalledWith({
          contactId: '123',
          kind: 'method',
          id: '3',
          archived: false,
        });
      });
    });

    it('says nothing is in use when every method is archived', () => {
      render(
        <ContactMethodsList contactId='123' methods={withArchived.slice(2)} />,
        { wrapper: createWrapper() }
      );

      expect(
        screen.getByText('No contact methods in use.')
      ).toBeInTheDocument();
    });
  });
});
