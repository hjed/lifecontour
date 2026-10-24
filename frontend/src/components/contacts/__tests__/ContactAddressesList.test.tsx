/**
 * @jest-environment jsdom
 */

import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ContactAddressesList } from '../ContactAddressesList';
import { ContactAddressResource } from '@/types/contacts';
import * as contactsApi from '@/lib/api/contacts';
import { PreconditionFailedError } from '@/lib/api/conditional-request';

// Mock the API functions
jest.mock('@/lib/api/contacts', () => ({
  useAddContactAddress: jest.fn(),
  useDeleteContactAddress: jest.fn(),
  useSetContactValueArchived: jest.fn(),
  useUpdateContactAddressFields: jest.fn(),
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
  const mockSetArchived = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();

    (contactsApi.useSetContactValueArchived as jest.Mock).mockReturnValue({
      mutateAsync: mockSetArchived,
      isPending: false,
    });

    (contactsApi.useAddContactAddress as jest.Mock).mockReturnValue({
      mutateAsync: mockAddAddress,
      isPending: false,
    });

    (contactsApi.useDeleteContactAddress as jest.Mock).mockReturnValue({
      mutateAsync: mockDeleteAddress,
      isPending: false,
    });

    (contactsApi.useUpdateContactAddressFields as jest.Mock).mockReturnValue({
      mutateAsync: mockUpdateField,
      isPending: false,
    });
  });

  it('renders addresses list with addresses', () => {
    render(<ContactAddressesList contactId='123' addresses={mockAddresses} />, {
      wrapper: createWrapper(),
    });

    expect(screen.getByText('Addresses')).toBeInTheDocument();
    expect(screen.getByText(/123 Main Street/)).toBeInTheDocument();
    expect(screen.getByText(/456 Business Ave/)).toBeInTheDocument();
  });

  it('renders empty state when no addresses', () => {
    render(<ContactAddressesList contactId='123' addresses={[]} />, {
      wrapper: createWrapper(),
    });

    expect(
      screen.getByText('No addresses yet. Click the + button to add one.')
    ).toBeInTheDocument();
  });

  it('shows add button', () => {
    render(<ContactAddressesList contactId='123' addresses={mockAddresses} />, {
      wrapper: createWrapper(),
    });

    const addButton = screen.getByLabelText('Add address');
    expect(addButton).toBeInTheDocument();
  });

  it('shows delete buttons for each address', () => {
    render(<ContactAddressesList contactId='123' addresses={mockAddresses} />, {
      wrapper: createWrapper(),
    });

    const deleteButtons = screen.getAllByLabelText('Delete address');
    expect(deleteButtons).toHaveLength(2);
  });

  it('calls delete address when delete button clicked and confirmed', async () => {
    render(<ContactAddressesList contactId='123' addresses={mockAddresses} />, {
      wrapper: createWrapper(),
    });

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
        addressId: '1',
      });
    });
  });

  it('does not delete when user cancels confirmation', async () => {
    render(<ContactAddressesList contactId='123' addresses={mockAddresses} />, {
      wrapper: createWrapper(),
    });

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
        contactId='123'
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
    render(<ContactAddressesList contactId='123' addresses={mockAddresses} />, {
      wrapper: createWrapper(),
    });

    expect(screen.getByText('Home')).toBeInTheDocument();
    expect(screen.getByText('Work')).toBeInTheDocument();
  });

  describe('archived addresses', () => {
    const withArchived: readonly ContactAddressResource[] = [
      ...mockAddresses,
      {
        id: '3',
        type: 'contact_addresses',
        attributes: {
          label: 'Childhood home',
          street_line_1: '1 Old Farm Road',
          locality: 'Bathurst',
          country_code: 'AU',
          is_primary: false,
          is_archived: true,
        },
      },
    ];

    it('keeps archived addresses behind a collapsed section', () => {
      render(
        <ContactAddressesList contactId='123' addresses={withArchived} />,
        { wrapper: createWrapper() }
      );

      expect(screen.queryByText(/1 Old Farm Road/)).not.toBeInTheDocument();

      fireEvent.click(
        screen.getByRole('button', { name: 'Archived addresses (1)' })
      );

      expect(screen.getByText(/1 Old Farm Road/)).toBeInTheDocument();
      expect(screen.getByText('Childhood home')).toBeInTheDocument();
    });

    it('offers the address editor on an archived address', () => {
      render(
        <ContactAddressesList contactId='123' addresses={withArchived} />,
        { wrapper: createWrapper() }
      );

      fireEvent.click(
        screen.getByRole('button', { name: 'Archived addresses (1)' })
      );

      expect(
        within(screen.getByTestId('archived-contact-address-3')).getByRole(
          'button',
          { name: 'Address (Childhood home)' }
        )
      ).toBeInTheDocument();
    });

    it('archives an active address and restores an archived one', async () => {
      render(
        <ContactAddressesList contactId='123' addresses={withArchived} />,
        { wrapper: createWrapper() }
      );

      fireEvent.click(
        screen.getAllByRole('button', { name: /^Archive address/ })[1]
      );
      fireEvent.click(
        screen.getByRole('button', { name: 'Archived addresses (1)' })
      );
      fireEvent.click(screen.getByRole('button', { name: /^Restore address/ }));

      await waitFor(() => {
        expect(mockSetArchived.mock.calls).toEqual([
          [{ kind: 'address', id: '2', archived: true }],
          [{ kind: 'address', id: '3', archived: false }],
        ]);
      });
    });
  });

  it('closes the add form when the add is refused as a conflict', async () => {
    // The conflict dialog holds the new value and can re-apply it; a form
    // left filled in would invite adding it twice.
    mockAddAddress.mockRejectedValueOnce(
      new PreconditionFailedError('moved on', 'PRECONDITION_FAILED', {})
    );
    render(<ContactAddressesList contactId='123' addresses={mockAddresses} />, {
      wrapper: createWrapper(),
    });

    fireEvent.click(screen.getByLabelText('Add address'));
    fireEvent.change(screen.getByPlaceholderText('123 Main Street'), {
      target: { value: '1 New Street' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add Address' }));

    await waitFor(() => expect(mockAddAddress).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: 'Add Address' })
      ).not.toBeInTheDocument()
    );
  });

  it('saves only the address fields the edit changed', async () => {
    // Re-sending the untouched fields would put back whatever this page last
    // read over a newer value saved elsewhere.
    mockUpdateField.mockResolvedValue(undefined);
    render(<ContactAddressesList contactId='123' addresses={mockAddresses} />, {
      wrapper: createWrapper(),
    });

    fireEvent.click(screen.getByRole('button', { name: 'Address (Home)' }));
    fireEvent.change(screen.getByLabelText('City'), {
      target: { value: 'Newcastle' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save address' }));

    await waitFor(() =>
      expect(mockUpdateField).toHaveBeenCalledWith({
        addressId: '1',
        fields: { locality: 'Newcastle' },
      })
    );
  });
});
