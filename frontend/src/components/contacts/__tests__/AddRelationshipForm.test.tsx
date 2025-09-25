/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AddRelationshipForm } from '../AddRelationshipForm';
import { RelationshipType } from '@/types/contacts';

// Mock the API hooks
const mockUseRelationshipTypes = jest.fn();

jest.mock('@/lib/api/relationships', () => ({
  useRelationshipTypes: () => mockUseRelationshipTypes(),
}));

// Mock ContactSearchCombobox
jest.mock('../ContactSearchCombobox', () => ({
  ContactSearchCombobox: function MockContactSearchCombobox({ onSelect, placeholder }: any) {
    return (
      <div>
        <input
          placeholder={placeholder}
          onChange={(e) => {
            if (e.target.value === 'test') {
              onSelect({
                type: 'contacts',
                id: '2',
                attributes: {
                  first_name: 'Jane',
                  last_name: 'Doe',
                  nick_name: null,
                  is_favourite: false,
                  created_at: '2024-01-01T00:00:00Z',
                  updated_at: '2024-01-01T00:00:00Z',
                  contact_methods: [],
                  addresses: [],
                  notes: [],
                  relationships: [],
                },
              });
            }
          }}
        />
      </div>
    );
  },
}));

// Mock toast
jest.mock('sonner', () => ({
  toast: {
    error: jest.fn(),
  },
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = 'TestWrapper';
  return Wrapper;
};

describe('AddRelationshipForm', () => {
  const mockOnSubmit = jest.fn();
  const mockOnCancel = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    mockUseRelationshipTypes.mockReturnValue({
      data: {
        relationship_types: [
          { value: 'partner', display_name: 'Partner' },
          { value: 'friend', display_name: 'Friend' },
          { value: 'family', display_name: 'Family' },
        ],
      },
      isLoading: false,
    });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('renders form title', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    expect(screen.getByText('Add New Relationship')).toBeInTheDocument();
  });

  it('renders contact search combobox', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    expect(screen.getByPlaceholderText('Search for a contact...')).toBeInTheDocument();
  });

  it('renders relationship type select', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    expect(screen.getByText('Relationship Type')).toBeInTheDocument();
  });

  it('renders submit and cancel buttons', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    expect(screen.getByText('Add Relationship')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('calls onCancel when cancel button clicked', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    const cancelButton = screen.getByText('Cancel');
    await user.click(cancelButton);

    expect(mockOnCancel).toHaveBeenCalled();
  });

  it('disables submit button when no contact selected', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    const submitButton = screen.getByText('Add Relationship');
    expect(submitButton).toBeDisabled();
  });

  it('enables submit button when contact and type selected', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    // Select a contact
    const searchInput = screen.getByPlaceholderText('Search for a contact...');
    await user.type(searchInput, 'test');

    // Wait for contact to be selected
    await waitFor(() => {
      expect(screen.getByText('Selected: Jane Doe')).toBeInTheDocument();
    });

    // Select relationship type
    const typeSelect = screen.getByRole('combobox');
    await user.click(typeSelect);

    // Wait for dropdown to open and select Friend
    await waitFor(() => {
      expect(screen.getByText('Friend')).toBeInTheDocument();
    });
    await user.click(screen.getByText('Friend'));

    const submitButton = screen.getByText('Add Relationship');
    expect(submitButton).not.toBeDisabled();
  });

  it('calls onSubmit with correct data when form submitted', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    // Select a contact
    const searchInput = screen.getByPlaceholderText('Search for a contact...');
    await user.type(searchInput, 'test');

    // Wait for contact to be selected
    await waitFor(() => {
      expect(screen.getByText('Selected: Jane Doe')).toBeInTheDocument();
    });

    // Select relationship type
    const typeSelect = screen.getByRole('combobox');
    await user.click(typeSelect);

    // Wait for dropdown and select Friend
    await waitFor(() => {
      expect(screen.getByText('Friend')).toBeInTheDocument();
    });
    await user.click(screen.getByText('Friend'));

    // Submit form
    const submitButton = screen.getByText('Add Relationship');
    await user.click(submitButton);

    expect(mockOnSubmit).toHaveBeenCalledWith({
      from_contact_id: 1,
      to_contact_id: 2,
      relationship_type: RelationshipType.FRIEND,
    });
  });

  it('shows validation error for missing contact', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    // Select relationship type only
    const typeSelect = screen.getByRole('combobox');
    await user.click(typeSelect);

    // Wait for dropdown and select Friend
    await waitFor(() => {
      expect(screen.getByText('Friend')).toBeInTheDocument();
    });
    await user.click(screen.getByText('Friend'));

    // Try to submit without selecting contact
    const submitButton = screen.getByText('Add Relationship');
    await user.click(submitButton);

    expect(mockOnSubmit).not.toHaveBeenCalled();
  });

  it('shows validation error for missing relationship type', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    // Select a contact only
    const searchInput = screen.getByPlaceholderText('Search for a contact...');
    await user.type(searchInput, 'test');

    // Wait for contact to be selected
    await waitFor(() => {
      expect(screen.getByText('Selected: Jane Doe')).toBeInTheDocument();
    });

    // Try to submit without selecting relationship type
    const submitButton = screen.getByText('Add Relationship');
    await user.click(submitButton);

    expect(mockOnSubmit).not.toHaveBeenCalled();
  });

  it('disables form when disabled prop is true', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
          disabled={true}
        />
      </Wrapper>
    );

    const submitButton = screen.getByText('Add Relationship');
    const cancelButton = screen.getByText('Cancel');

    expect(submitButton).toBeDisabled();
    expect(cancelButton).toBeDisabled();
  });

  it('shows loading state for relationship types', () => {
    mockUseRelationshipTypes.mockReturnValue({
      data: null,
      isLoading: true,
    });

    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    expect(screen.getByText('Loading relationship types...')).toBeInTheDocument();
  });

  it('resets form after successful submission', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId="1"
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    // Fill form
    const searchInput = screen.getByPlaceholderText('Search for a contact...');
    await user.type(searchInput, 'test');

    // Wait for contact to be selected
    await waitFor(() => {
      expect(screen.getByText('Selected: Jane Doe')).toBeInTheDocument();
    });

    const typeSelect = screen.getByRole('combobox');
    await user.click(typeSelect);

    // Wait for dropdown and select Friend
    await waitFor(() => {
      expect(screen.getByText('Friend')).toBeInTheDocument();
    });
    await user.click(screen.getByText('Friend'));

    // Submit form
    const submitButton = screen.getByText('Add Relationship');
    await user.click(submitButton);

    // Form should be reset (submit button disabled again)
    expect(submitButton).toBeDisabled();
  });
});
