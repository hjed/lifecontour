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

  beforeEach(() => {
    jest.clearAllMocks();

    (contactsApi.useAddContactMethod as jest.Mock).mockReturnValue({
      mutateAsync: mockAddMethod,
      isPending: false,
    });

    (contactsApi.useDeleteContactMethod as jest.Mock).mockReturnValue({
      mutateAsync: mockDeleteMethod,
      isPending: false,
    });

    (contactsApi.updateContactMethodField as jest.Mock).mockImplementation(mockUpdateField);
  });

  it('renders contact methods list with methods', () => {
    render(
      <ContactMethodsList
        contactId="123"
        methods={mockMethods}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText('Contact Methods')).toBeInTheDocument();
    expect(screen.getByText('john@example.com')).toBeInTheDocument();
    expect(screen.getByText('+61 2 1234 5678')).toBeInTheDocument();
  });

  it('renders empty state when no methods', () => {
    render(
      <ContactMethodsList
        contactId="123"
        methods={[]}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText('No contact methods yet. Click the + button to add one.')).toBeInTheDocument();
  });

  it('shows add button', () => {
    render(
      <ContactMethodsList
        contactId="123"
        methods={mockMethods}
      />,
      { wrapper: createWrapper() }
    );

    const addButton = screen.getByLabelText('Add contact method');
    expect(addButton).toBeInTheDocument();
  });

  it('shows delete buttons for each method', () => {
    render(
      <ContactMethodsList
        contactId="123"
        methods={mockMethods}
      />,
      { wrapper: createWrapper() }
    );

    const deleteButtons = screen.getAllByLabelText(/Delete/);
    expect(deleteButtons).toHaveLength(2);
  });

  it('calls delete method when delete button clicked and confirmed', async () => {
    render(
      <ContactMethodsList
        contactId="123"
        methods={mockMethods}
      />,
      { wrapper: createWrapper() }
    );

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
    render(
      <ContactMethodsList
        contactId="123"
        methods={mockMethods}
      />,
      { wrapper: createWrapper() }
    );

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
        contactId="123"
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
});
