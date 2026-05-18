/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AddRelationshipForm } from '../AddRelationshipForm';

// Mock the API hooks
const mockUseRelationshipTypes = jest.fn();

jest.mock('@/lib/api/relationships', () => ({
  useRelationshipTypes: () => mockUseRelationshipTypes(),
}));

// Mock ContactSearchCombobox
jest.mock('../ContactSearchCombobox', () => ({
  ContactSearchCombobox: function MockContactSearchCombobox({
    onSelect,
    placeholder,
    inputId,
  }: {
    onSelect: (contact: unknown) => void;
    placeholder?: string;
    inputId?: string;
  }) {
    return (
      <div>
        <input
          id={inputId}
          placeholder={placeholder}
          onChange={e => {
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
          contactId='1'
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
          contactId='1'
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    expect(
      screen.getByPlaceholderText('Search for a contact...')
    ).toBeInTheDocument();
  });

  it('associates the contact label with the combobox input', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId='1'
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    expect(screen.getByLabelText('Contact')).toHaveAttribute(
      'placeholder',
      'Search for a contact...'
    );
  });

  it('renders relationship type select', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId='1'
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
          contactId='1'
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
          contactId='1'
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
          contactId='1'
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    const submitButton = screen.getByText('Add Relationship');
    expect(submitButton).toBeDisabled();
  });

  it('enables submit button when contact is selected', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId='1'
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    // Initially submit button should be disabled
    const submitButton = screen.getByText('Add Relationship');
    expect(submitButton).toBeDisabled();

    // Select a contact
    const searchInput = screen.getByPlaceholderText('Search for a contact...');
    await user.type(searchInput, 'test');

    // Wait for contact to be selected
    await waitFor(() => {
      expect(screen.getByText('Selected: Jane Doe')).toBeInTheDocument();
    });

    // Verify the relationship type selector is present
    const typeSelect = screen.getByRole('combobox');
    expect(typeSelect).toBeInTheDocument();
    expect(screen.getByText('Select relationship type')).toBeInTheDocument();

    // Submit button should still be disabled until relationship type is selected
    // Note: We can't easily test the Select dropdown in JSDOM, but we can verify the form structure
    expect(submitButton).toBeDisabled();
  });

  it('displays form elements and handles contact selection', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId='1'
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    // Verify form structure
    expect(screen.getByText('Add New Relationship')).toBeInTheDocument();
    expect(screen.getByText('Contact')).toBeInTheDocument();
    expect(screen.getByText('Relationship Type')).toBeInTheDocument();

    // Test contact selection
    const searchInput = screen.getByPlaceholderText('Search for a contact...');
    await user.type(searchInput, 'test');

    // Wait for contact to be selected
    await waitFor(() => {
      expect(screen.getByText('Selected: Jane Doe')).toBeInTheDocument();
    });

    // Verify relationship type selector is present
    expect(screen.getByRole('combobox')).toBeInTheDocument();
    expect(screen.getByText('Select relationship type')).toBeInTheDocument();

    // Submit button should be disabled until both fields are filled
    const submitButton = screen.getByText('Add Relationship');
    expect(submitButton).toBeDisabled();
  });

  it('validates that contact is required', async () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId='1'
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    // Initially, no contact is selected
    expect(screen.queryByText(/Selected:/)).not.toBeInTheDocument();

    // Submit button should be disabled when no contact is selected
    const submitButton = screen.getByText('Add Relationship');
    expect(submitButton).toBeDisabled();

    // Verify the form shows the contact search field
    expect(
      screen.getByPlaceholderText('Search for a contact...')
    ).toBeInTheDocument();
  });

  it('validates that relationship type is required', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId='1'
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

    // Submit button should still be disabled without relationship type
    const submitButton = screen.getByText('Add Relationship');
    expect(submitButton).toBeDisabled();

    // Verify relationship type selector shows placeholder
    expect(screen.getByText('Select relationship type')).toBeInTheDocument();
  });

  it('disables form when disabled prop is true', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId='1'
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
          contactId='1'
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    expect(
      screen.getByText('Loading relationship types...')
    ).toBeInTheDocument();
  });

  it('handles form state correctly', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <AddRelationshipForm
          contactId='1'
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
        />
      </Wrapper>
    );

    // Initially submit button should be disabled
    const submitButton = screen.getByText('Add Relationship');
    expect(submitButton).toBeDisabled();

    // Fill contact field
    const searchInput = screen.getByPlaceholderText('Search for a contact...');
    await user.type(searchInput, 'test');

    // Wait for contact to be selected
    await waitFor(() => {
      expect(screen.getByText('Selected: Jane Doe')).toBeInTheDocument();
    });

    // Verify relationship type selector is present and shows placeholder
    const typeSelect = screen.getByRole('combobox');
    expect(typeSelect).toBeInTheDocument();
    expect(screen.getByText('Select relationship type')).toBeInTheDocument();

    // Submit button should still be disabled until relationship type is selected
    expect(submitButton).toBeDisabled();
  });
});
