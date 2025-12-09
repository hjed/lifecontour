/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ContactAddressesList } from '../ContactAddressesList';
import { ContactAddressResource } from '@/types/contacts';
import * as contactsApi from '@/lib/api/contacts';

// Mock the API functions
jest.mock('@/lib/api/contacts', () => ({
  useAddContactAddress: jest.fn(),
  useDeleteContactAddress: jest.fn(),
  updateContactAddressField: jest.fn(),
}));

// Mock toast
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const mockAddresses: readonly ContactAddressResource[] = [
  {
    id: '1',
    type: 'contact_addresses',
    attributes: {
      label: 'Home',
      street_line_1: '123 Main Street',
      street_line_2: 'Apt 4B',
      locality: 'Sydney',
      region: 'NSW',
      postal_code: '2000',
      country_code: 'AU',
      is_primary: true,
    },
  },
  {
    id: '2',
    type: 'contact_addresses',
    attributes: {
      label: 'Work',
      street_line_1: '456 Business Ave',
      locality: 'Melbourne',
      region: 'VIC',
      postal_code: '3000',
      country_code: 'AU',
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

describe('ContactAddressesList', () => {
  const mockAddAddress = jest.fn();
  const mockDeleteAddress = jest.fn();
  const mockUpdateField = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();

    (contactsApi.useAddContactAddress as jest.Mock).mockReturnValue({
      mutateAsync: mockAddAddress,
      isPending: false,
    });

    (contactsApi.useDeleteContactAddress as jest.Mock).mockReturnValue({
      mutateAsync: mockDeleteAddress,
      isPending: false,
    });

    (contactsApi.updateContactAddressField as jest.Mock).mockImplementation(mockUpdateField);
  });

  it('renders addresses list with addresses', () => {
    render(
      <ContactAddressesList
        contactId="123"
        addresses={mockAddresses}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText('Addresses')).toBeInTheDocument();
    expect(screen.getByText(/123 Main Street/)).toBeInTheDocument();
    expect(screen.getByText(/456 Business Ave/)).toBeInTheDocument();
  });

  it('renders empty state when no addresses', () => {
    render(
      <ContactAddressesList
        contactId="123"
        addresses={[]}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText('No addresses yet. Click the + button to add one.')).toBeInTheDocument();
  });

  it('shows add button', () => {
    render(
      <ContactAddressesList
        contactId="123"
        addresses={mockAddresses}
      />,
      { wrapper: createWrapper() }
    );

    const addButton = screen.getByLabelText('Add address');
    expect(addButton).toBeInTheDocument();
  });

  it('shows delete buttons for each address', () => {
    render(
      <ContactAddressesList
        contactId="123"
        addresses={mockAddresses}
      />,
      { wrapper: createWrapper() }
    );

    const deleteButtons = screen.getAllByLabelText('Delete address');
    expect(deleteButtons).toHaveLength(2);
  });

  it('calls delete address when delete button clicked and confirmed', async () => {
    render(
      <ContactAddressesList
        contactId="123"
        addresses={mockAddresses}
      />,
      { wrapper: createWrapper() }
    );

    // Click the delete button to open the dialog
    const deleteButton = screen.getAllByLabelText('Delete address')[0];
    fireEvent.click(deleteButton);

    // Wait for the dialog to appear and click the confirm button
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    const confirmButton = screen.getByRole('button', { name: 'Delete' });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(mockDeleteAddress).toHaveBeenCalledWith({
        contactId: '123',
        addressId: '1',
      });
    });
  });

  it('does not delete when user cancels confirmation', async () => {
    render(
      <ContactAddressesList
        contactId="123"
        addresses={mockAddresses}
      />,
      { wrapper: createWrapper() }
    );

    // Click the delete button to open the dialog
    const deleteButton = screen.getAllByLabelText('Delete address')[0];
    fireEvent.click(deleteButton);

    // Wait for the dialog to appear and click the cancel button
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    const cancelButton = screen.getByRole('button', { name: 'Cancel' });
    fireEvent.click(cancelButton);

    await waitFor(() => {
      expect(mockDeleteAddress).not.toHaveBeenCalled();
    });
  });

  it('disables buttons when disabled prop is true', () => {
    render(
      <ContactAddressesList
        contactId="123"
        addresses={mockAddresses}
        disabled={true}
      />,
      { wrapper: createWrapper() }
    );

    const addButton = screen.getByLabelText('Add address');
    const deleteButtons = screen.getAllByLabelText('Delete address');

    expect(addButton).toBeDisabled();
    deleteButtons.forEach(button => {
      expect(button).toBeDisabled();
    });
  });

  it('displays address labels when present', () => {
    render(
      <ContactAddressesList
        contactId="123"
        addresses={mockAddresses}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText('Home')).toBeInTheDocument();
    expect(screen.getByText('Work')).toBeInTheDocument();
  });
});
