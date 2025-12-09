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
    id: 1,
    type: 'contact_methods',
    attributes: {
      method_type: ContactMethodType.EMAIL,
      value: 'john@example.com',
      label: 'Work',
      is_primary: true,
    },
  },
  {
    id: 2,
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
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe('ContactMethodsList', () => {
  const mockAddMethod = jest.fn();
  const mockDeleteMethod = jest.fn();
  const mockUpdateField = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    
    (contactsApi.useAddContactMethod as jest.Mock).mockReturnValue({
      mutateAsync: mockAddMethod,
    });
    
    (contactsApi.useDeleteContactMethod as jest.Mock).mockReturnValue({
      mutateAsync: mockDeleteMethod,
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
    expect(screen.getByDisplayValue('john@example.com')).toBeInTheDocument();
    expect(screen.getByDisplayValue('+61-2-1234-5678')).toBeInTheDocument();
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
    // Mock window.confirm to return true
    const originalConfirm = window.confirm;
    window.confirm = jest.fn(() => true);

    render(
      <ContactMethodsList
        contactId="123"
        methods={mockMethods}
      />,
      { wrapper: createWrapper() }
    );

    const deleteButton = screen.getByLabelText('Delete email');
    fireEvent.click(deleteButton);

    await waitFor(() => {
      expect(mockDeleteMethod).toHaveBeenCalledWith({
        contactId: '123',
        methodId: '1',
      });
    });

    // Restore original confirm
    window.confirm = originalConfirm;
  });

  it('does not delete when user cancels confirmation', async () => {
    // Mock window.confirm to return false
    const originalConfirm = window.confirm;
    window.confirm = jest.fn(() => false);

    render(
      <ContactMethodsList
        contactId="123"
        methods={mockMethods}
      />,
      { wrapper: createWrapper() }
    );

    const deleteButton = screen.getByLabelText('Delete email');
    fireEvent.click(deleteButton);

    await waitFor(() => {
      expect(mockDeleteMethod).not.toHaveBeenCalled();
    });

    // Restore original confirm
    window.confirm = originalConfirm;
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
