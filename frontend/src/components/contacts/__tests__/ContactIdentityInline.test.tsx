/**
 * Tests for ContactIdentityInline component.
 *
 * Tests the inline editing functionality for contact name and nickname fields.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ContactIdentityInline } from '@/components/contacts/ContactIdentityInline';
import type { ContactResource } from '@/types/contacts';

// Mock the API hook
const mockMutateAsync = jest.fn();
jest.mock('@/lib/api/contacts', () => ({
  useUpdateContactField: () => ({
    mutateAsync: mockMutateAsync,
  }),
}));

// Mock the FavouriteToggle component
jest.mock('@/components/contacts/FavouriteToggle', () => ({
  FavouriteToggle: ({ contactName }: { contactName: string }) => (
    <div data-testid='favourite-toggle'>Favourite: {contactName}</div>
  ),
}));

// Mock toast notifications
jest.mock('sonner', () => ({
  toast: {
    error: jest.fn(),
    success: jest.fn(),
  },
}));

describe('ContactIdentityInline', () => {
  let queryClient: QueryClient;

  const mockContact: ContactResource = {
    id: '1',
    type: 'contacts',
    attributes: {
      first_name: 'John',
      last_name: 'Doe',
      nick_name: 'Johnny',
      is_favourite: false,
      created_at: '2023-01-01T00:00:00Z',
      updated_at: '2023-01-01T00:00:00Z',
      contact_methods: [],
      addresses: [],
      notes: [],
    },
    relationships: {},
  };

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    jest.clearAllMocks();
  });

  const renderComponent = (contact = mockContact) => {
    return render(
      <QueryClientProvider client={queryClient}>
        <ContactIdentityInline contact={contact} />
      </QueryClientProvider>
    );
  };

  describe('display', () => {
    it('should render contact name fields', () => {
      renderComponent();

      expect(screen.getByText('John')).toBeInTheDocument();
      expect(screen.getByText('Doe')).toBeInTheDocument();
    });

    it('should render nickname field', () => {
      renderComponent();

      expect(screen.getByText('Johnny')).toBeInTheDocument();
    });

    it('should render favourite toggle', () => {
      renderComponent();

      expect(screen.getByTestId('favourite-toggle')).toBeInTheDocument();
      expect(screen.getByText('Favourite: John Doe')).toBeInTheDocument();
    });

    it('should handle missing last name', () => {
      const contactWithoutLastName = {
        ...mockContact,
        attributes: {
          ...mockContact.attributes,
          last_name: '',
        },
      };

      renderComponent(contactWithoutLastName);

      expect(screen.getByText('John')).toBeInTheDocument();
      expect(screen.getByText('Favourite: John')).toBeInTheDocument();
    });

    it('should handle missing nickname', () => {
      const contactWithoutNickname = {
        ...mockContact,
        attributes: {
          ...mockContact.attributes,
          nick_name: '',
        },
      };

      renderComponent(contactWithoutNickname);

      expect(screen.getByText('Add nickname')).toBeInTheDocument();
    });
  });

  describe('inline editing', () => {
    it('should save first name changes', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValue({});

      renderComponent();

      const firstNameField = screen.getByText('John');
      await user.click(firstNameField);

      const input = screen.getByRole('textbox');
      await user.clear(input);
      await user.type(input, 'Jane');

      const saveButton = screen.getByRole('button', { name: /save/i });
      await user.click(saveButton);

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith({
          contactId: '1',
          fieldName: 'first_name',
          value: 'Jane',
        });
      });
    });

    it('should save last name changes', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValue({});

      renderComponent();

      const lastNameField = screen.getByText('Doe');
      await user.click(lastNameField);

      const input = screen.getByRole('textbox');
      await user.clear(input);
      await user.type(input, 'Smith');

      const saveButton = screen.getByRole('button', { name: /save/i });
      await user.click(saveButton);

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith({
          contactId: '1',
          fieldName: 'last_name',
          value: 'Smith',
        });
      });
    });

    it('should save nickname changes', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValue({});

      renderComponent();

      const nicknameField = screen.getByText('Johnny');
      await user.click(nicknameField);

      const input = screen.getByRole('textbox');
      await user.clear(input);
      await user.type(input, 'JD');

      const saveButton = screen.getByRole('button', { name: /save/i });
      await user.click(saveButton);

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith({
          contactId: '1',
          fieldName: 'nick_name',
          value: 'JD',
        });
      });
    });

    it('should validate required first name', async () => {
      const user = userEvent.setup();

      renderComponent();

      const firstNameField = screen.getByText('John');
      await user.click(firstNameField);

      const input = screen.getByRole('textbox');
      await user.clear(input);

      const saveButton = screen.getByRole('button', { name: /save/i });
      await user.click(saveButton);

      expect(screen.getByText('This field is required')).toBeInTheDocument();
      expect(mockMutateAsync).not.toHaveBeenCalled();
    });

    it('should handle save errors gracefully', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockRejectedValue(new Error('Save failed'));

      renderComponent();

      const firstNameField = screen.getByText('John');
      await user.click(firstNameField);

      const input = screen.getByRole('textbox');
      await user.clear(input);
      await user.type(input, 'Jane');

      const saveButton = screen.getByRole('button', { name: /save/i });
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText('Save failed')).toBeInTheDocument();
      });
    });
  });

  describe('accessibility', () => {
    it('should have proper ARIA labels', () => {
      renderComponent();

      const firstNameField = screen.getByLabelText('First name');
      const lastNameField = screen.getByLabelText('Last name');
      const nicknameField = screen.getByLabelText('Nickname');

      expect(firstNameField).toBeInTheDocument();
      expect(lastNameField).toBeInTheDocument();
      expect(nicknameField).toBeInTheDocument();
    });

    it('should have proper test IDs', () => {
      renderComponent();

      expect(screen.getByTestId('first-name-field')).toBeInTheDocument();
      expect(screen.getByTestId('last-name-field')).toBeInTheDocument();
      expect(screen.getByTestId('nickname-field')).toBeInTheDocument();
    });
  });
});
