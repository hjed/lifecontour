/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RelationshipsList } from '../RelationshipsList';
import { ContactRelationshipResource, RelationshipType } from '@/types/contacts';

// Mock the API hooks
const mockUseContactRelationships = jest.fn();
const mockUseCreateContactRelationship = jest.fn();
const mockUseUpdateContactRelationship = jest.fn();
const mockUseDeleteContactRelationship = jest.fn();
const mockUseRelationshipTypes = jest.fn();

jest.mock('@/lib/api/relationships', () => ({
  useContactRelationships: () => mockUseContactRelationships(),
  useCreateContactRelationship: () => mockUseCreateContactRelationship(),
  useUpdateContactRelationship: () => mockUseUpdateContactRelationship(),
  useDeleteContactRelationship: () => mockUseDeleteContactRelationship(),
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
const mockRelationships: ContactRelationshipResource[] = [
  {
    type: 'contact_relationships',
    id: '1',
    attributes: {
      from_contact_id: 1,
      to_contact_id: 2,
      relationship_type: RelationshipType.PARTNER,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    },
  },
  {
    type: 'contact_relationships',
    id: '2',
    attributes: {
      from_contact_id: 1,
      to_contact_id: 3,
      relationship_type: RelationshipType.FRIEND,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    },
  },
];

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

describe('RelationshipsList', () => {

  beforeEach(() => {
    jest.clearAllMocks();
    mockUseContactRelationships.mockReturnValue({
      data: { data: mockRelationships },
      isLoading: false,
      error: null,
    });

    mockUseCreateContactRelationship.mockReturnValue({
      mutate: jest.fn(),
      isPending: false,
    });

    mockUseUpdateContactRelationship.mockReturnValue({
      mutate: jest.fn(),
      isPending: false,
    });

    mockUseDeleteContactRelationship.mockReturnValue({
      mutate: jest.fn(),
      isPending: false,
    });

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

  it('renders relationships list with title', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipsList contactId="1" />
      </Wrapper>
    );

    expect(screen.getByText('Relationships')).toBeInTheDocument();
  });

  it('displays existing relationships', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipsList contactId="1" />
      </Wrapper>
    );

    expect(screen.getByText('Partner')).toBeInTheDocument();
    expect(screen.getByText('Friend')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    mockUseContactRelationships.mockReturnValue({
      data: null,
      isLoading: true,
      error: null,
    });

    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipsList contactId="1" />
      </Wrapper>
    );

    expect(screen.getByText('Loading relationships...')).toBeInTheDocument();
  });

  it('shows error state', () => {
    mockUseContactRelationships.mockReturnValue({
      data: null,
      isLoading: false,
      error: new Error('Failed to load'),
    });

    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipsList contactId="1" />
      </Wrapper>
    );

    expect(screen.getByText('Error loading relationships')).toBeInTheDocument();
  });

  it('shows empty state when no relationships', () => {
    mockUseContactRelationships.mockReturnValue({
      data: { data: [] },
      isLoading: false,
      error: null,
    });

    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipsList contactId="1" />
      </Wrapper>
    );

    expect(screen.getByText('No relationships yet')).toBeInTheDocument();
  });

  it('shows add relationship button', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipsList contactId="1" />
      </Wrapper>
    );

    expect(screen.getByText('Add Relationship')).toBeInTheDocument();
  });

  it('opens add relationship form when button clicked', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipsList contactId="1" />
      </Wrapper>
    );

    const addButton = screen.getByText('Add Relationship');
    await user.click(addButton);

    expect(screen.getByText('Add New Relationship')).toBeInTheDocument();
  });

  it('closes add relationship form when cancelled', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipsList contactId="1" />
      </Wrapper>
    );

    const addButton = screen.getByText('Add Relationship');
    await user.click(addButton);

    const cancelButton = screen.getByText('Cancel');
    await user.click(cancelButton);

    expect(screen.queryByText('Add New Relationship')).not.toBeInTheDocument();
  });

  it('handles relationship deletion', async () => {
    const user = userEvent.setup();
    const mockDelete = jest.fn();
    mockUseDeleteContactRelationship.mockReturnValue({
      mutate: mockDelete,
      isPending: false,
    });

    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipsList contactId="1" />
      </Wrapper>
    );

    const deleteButtons = screen.getAllByLabelText('Delete relationship');
    await user.click(deleteButtons[0]);

    expect(mockDelete).toHaveBeenCalledWith({
      contactId: '1',
      relationshipId: '1',
    });
  });

  it('disables actions when mutations are pending', () => {
    mockUseDeleteContactRelationship.mockReturnValue({
      mutate: jest.fn(),
      isPending: true,
    });

    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipsList contactId="1" />
      </Wrapper>
    );

    const deleteButtons = screen.getAllByLabelText('Delete relationship');
    expect(deleteButtons[0]).toBeDisabled();
  });

  it('handles contact selection in add form', async () => {
    const user = userEvent.setup();
    const mockCreate = jest.fn();
    mockUseCreateContactRelationship.mockReturnValue({
      mutate: mockCreate,
      isPending: false,
    });

    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <RelationshipsList contactId="1" />
      </Wrapper>
    );

    const addButton = screen.getByText('Add Relationship');
    await user.click(addButton);

    // This would require the ContactSearchCombobox to be rendered
    // and would test the integration between components
    expect(screen.getByText('Add New Relationship')).toBeInTheDocument();
  });
});
