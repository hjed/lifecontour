/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RelationshipItem } from '../RelationshipItem';
import {
  ContactRelationshipResource,
  RelationshipType,
} from '@/types/contacts';

// Mock the API hooks
const mockUseRelationshipTypes = jest.fn();

jest.mock('@/lib/api/relationships', () => ({
  useRelationshipTypes: () => mockUseRelationshipTypes(),
}));

// Mock toast
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

// Test data
const mockRelationship: ContactRelationshipResource = {
  type: 'contact_relationships',
  id: '1',
  attributes: {
    from_contact_id: 1,
    to_contact_id: 2,
    to_contact_name: 'Jane Smith',
    to_user: false,
    relationship_type: RelationshipType.PARTNER,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
};

const mockUserTargetedRelationship: ContactRelationshipResource = {
  type: 'contact_relationships',
  id: '2',
  attributes: {
    from_contact_id: 1,
    to_contact_id: null,
    to_contact_name: undefined,
    to_user: true,
    relationship_type: RelationshipType.FRIEND,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
};

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

describe('RelationshipItem', () => {
  const mockOnUpdate = jest.fn();
  const mockOnDelete = jest.fn();

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

  it('renders relationship type', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={mockRelationship}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    expect(screen.getByText('Partner')).toBeInTheDocument();
  });

  it('renders linked contact name as a link', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={mockRelationship}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    const contactLink = screen.getByText('Jane Smith');
    expect(contactLink).toBeInTheDocument();
    expect(contactLink).toHaveAttribute('href', '/contacts/2');
  });

  it('links to from_contact_id when current contact is the to_contact', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={mockRelationship}
          currentContactId='2'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    const contactLink = screen.getByText('Jane Smith');
    expect(contactLink).toHaveAttribute('href', '/contacts/1');
  });

  it('renders without contact name when not provided', () => {
    const relationshipWithoutName: ContactRelationshipResource = {
      ...mockRelationship,
      attributes: {
        ...mockRelationship.attributes,
        to_contact_name: undefined,
      },
    };

    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={relationshipWithoutName}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    expect(screen.getByText('Partner')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('shows edit and delete buttons', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={mockRelationship}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    expect(screen.getByLabelText('Edit relationship')).toBeInTheDocument();
    expect(screen.getByLabelText('Delete relationship')).toBeInTheDocument();
  });

  it('enters edit mode when edit button clicked', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={mockRelationship}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    const editButton = screen.getByLabelText('Edit relationship');
    await user.click(editButton);

    expect(screen.getByText('Partner')).toBeInTheDocument(); // Select shows current value
    expect(screen.getByText('Save')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('calls onDelete when delete button clicked', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={mockRelationship}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    const deleteButton = screen.getByLabelText('Delete relationship');
    await user.click(deleteButton);

    expect(mockOnDelete).toHaveBeenCalled();
  });

  it('calls onUpdate when save button clicked in edit mode', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={mockRelationship}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    const editButton = screen.getByLabelText('Edit relationship');
    await user.click(editButton);

    // Just test that save button calls onUpdate with current data
    // (avoiding complex Select component interaction)
    const saveButton = screen.getByText('Save');
    await user.click(saveButton);

    expect(mockOnUpdate).toHaveBeenCalledWith({
      from_contact_id: 1,
      to_contact_id: 2,
      to_user: false,
      relationship_type: RelationshipType.PARTNER, // Current value
    });
  });

  it('cancels edit mode when cancel button clicked', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={mockRelationship}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    const editButton = screen.getByLabelText('Edit relationship');
    await user.click(editButton);

    const cancelButton = screen.getByText('Cancel');
    await user.click(cancelButton);

    expect(screen.getByText('Partner')).toBeInTheDocument();
    expect(screen.queryByText('Save')).not.toBeInTheDocument();
  });

  it('disables buttons when disabled prop is true', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={mockRelationship}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
          disabled={true}
        />
      </Wrapper>
    );

    expect(screen.getByLabelText('Edit relationship')).toBeDisabled();
    expect(screen.getByLabelText('Delete relationship')).toBeDisabled();
  });

  it('shows loading state for relationship types', () => {
    mockUseRelationshipTypes.mockReturnValue({
      data: null,
      isLoading: true,
    });

    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={mockRelationship}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    const editButton = screen.getByLabelText('Edit relationship');
    fireEvent.click(editButton);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('handles unknown relationship type gracefully', () => {
    const relationshipWithUnknownType = {
      ...mockRelationship,
      attributes: {
        ...mockRelationship.attributes,
        relationship_type: 'unknown' as RelationshipType,
      },
    };

    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={relationshipWithUnknownType}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    expect(screen.getByText('unknown')).toBeInTheDocument();
  });

  it('validates relationship type selection', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipItem
          relationship={mockRelationship}
          currentContactId='1'
          onUpdate={mockOnUpdate}
          onDelete={mockOnDelete}
        />
      </Wrapper>
    );

    const editButton = screen.getByLabelText('Edit relationship');
    await user.click(editButton);

    // Try to save without changing the selection (should still be valid)
    const saveButton = screen.getByText('Save');
    await user.click(saveButton);

    // Should call onUpdate with current valid data
    expect(mockOnUpdate).toHaveBeenCalledWith({
      from_contact_id: 1,
      to_contact_id: 2,
      to_user: false,
      relationship_type: RelationshipType.PARTNER,
    });
  });

  // User-targeted relationship tests
  describe('user-targeted relationships', () => {
    it('displays "You" as a span instead of a link for user-targeted relationships', () => {
      const Wrapper = createWrapper();
      render(
        <Wrapper>
          <RelationshipItem
            relationship={mockUserTargetedRelationship}
            currentContactId='1'
            onUpdate={mockOnUpdate}
            onDelete={mockOnDelete}
          />
        </Wrapper>
      );

      const youText = screen.getByTestId('relationship-user-target');
      expect(youText).toHaveTextContent('You');
      // Should NOT be a link
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
    });

    it('renders relationship type for user-targeted relationships', () => {
      const Wrapper = createWrapper();
      render(
        <Wrapper>
          <RelationshipItem
            relationship={mockUserTargetedRelationship}
            currentContactId='1'
            onUpdate={mockOnUpdate}
            onDelete={mockOnDelete}
          />
        </Wrapper>
      );

      expect(screen.getByText('Friend')).toBeInTheDocument();
    });

    it('passes to_user flag in update data for user-targeted relationships', async () => {
      const user = userEvent.setup();
      const Wrapper = createWrapper();
      render(
        <Wrapper>
          <RelationshipItem
            relationship={mockUserTargetedRelationship}
            currentContactId='1'
            onUpdate={mockOnUpdate}
            onDelete={mockOnDelete}
          />
        </Wrapper>
      );

      const editButton = screen.getByLabelText('Edit relationship');
      await user.click(editButton);

      const saveButton = screen.getByText('Save');
      await user.click(saveButton);

      expect(mockOnUpdate).toHaveBeenCalledWith({
        from_contact_id: 1,
        to_contact_id: undefined,
        to_user: true,
        relationship_type: RelationshipType.FRIEND,
      });
    });
  });
});
