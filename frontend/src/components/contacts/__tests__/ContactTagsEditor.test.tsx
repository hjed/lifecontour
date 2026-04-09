/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { ContactTagsEditor } from '../ContactTagsEditor';
import {
  useContactTags,
  useTags,
  useAssignContactTag,
  useRemoveContactTag,
  useCreateTag,
} from '@/lib/api/contacts';
import type { TagResource, TagListResponse } from '@/types/contacts';

// Mock constants
jest.mock('@/lib/constants', () => ({
  TAG_COLORS: [
    '#E53E3E',
    '#DD6B20',
    '#D69E2E',
    '#38A169',
    '#319795',
    '#3182CE',
    '#805AD5',
    '#D53F8C',
    '#718096',
    '#2D3748',
  ],
}));

// Mock the API hooks
jest.mock('@/lib/api/contacts', () => ({
  useContactTags: jest.fn(),
  useTags: jest.fn(),
  useAssignContactTag: jest.fn(),
  useRemoveContactTag: jest.fn(),
  useCreateTag: jest.fn(),
}));

const mockUseContactTags = useContactTags as jest.MockedFunction<
  typeof useContactTags
>;
const mockUseTags = useTags as jest.MockedFunction<typeof useTags>;
const mockUseAssignContactTag = useAssignContactTag as jest.MockedFunction<
  typeof useAssignContactTag
>;
const mockUseRemoveContactTag = useRemoveContactTag as jest.MockedFunction<
  typeof useRemoveContactTag
>;
const mockUseCreateTag = useCreateTag as jest.MockedFunction<
  typeof useCreateTag
>;

function createTag(
  id: string,
  name: string,
  color?: string,
  parentId?: number | null
): TagResource {
  return {
    type: 'tags',
    id,
    attributes: {
      name,
      color: color ?? null,
      parent_id: parentId ?? null,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    },
  } as TagResource;
}

function createTagListResponse(tags: TagResource[]): TagListResponse {
  return { data: tags };
}

describe('ContactTagsEditor', () => {
  const mockAssignMutate = jest.fn();
  const mockRemoveMutate = jest.fn();
  const mockCreateMutateAsync = jest.fn();

  const assignedTags = [
    createTag('1', 'Work', '#3182CE'),
    createTag('2', 'Family', '#38A169'),
  ];

  const allTags = [
    ...assignedTags,
    createTag('3', 'Friends', '#D53F8C'),
    createTag('4', 'Business', '#805AD5', 1), // child of Work
  ];

  beforeEach(() => {
    jest.clearAllMocks();

    mockUseContactTags.mockReturnValue({
      data: createTagListResponse(assignedTags),
      isLoading: false,
      isError: false,
    } as any);

    mockUseTags.mockReturnValue({
      data: createTagListResponse(allTags),
      isLoading: false,
    } as any);

    mockUseAssignContactTag.mockReturnValue({
      mutate: mockAssignMutate,
      isPending: false,
    } as any);

    mockUseRemoveContactTag.mockReturnValue({
      mutate: mockRemoveMutate,
      isPending: false,
    } as any);

    mockUseCreateTag.mockReturnValue({
      mutateAsync: mockCreateMutateAsync,
      isPending: false,
    } as any);
  });

  it('should render assigned tags as badges', () => {
    render(<ContactTagsEditor contactId='42' />);

    expect(screen.getByTestId('tag-badge-1')).toHaveTextContent('Work');
    expect(screen.getByTestId('tag-badge-2')).toHaveTextContent('Family');
  });

  it('should show remove button on each tag badge', () => {
    render(<ContactTagsEditor contactId='42' />);

    expect(screen.getByTestId('remove-tag-1')).toBeInTheDocument();
    expect(screen.getByTestId('remove-tag-2')).toBeInTheDocument();
  });

  it('should call removeTagFromContact when X is clicked', async () => {
    const user = userEvent.setup();
    render(<ContactTagsEditor contactId='42' />);

    await user.click(screen.getByTestId('remove-tag-1'));

    expect(mockRemoveMutate).toHaveBeenCalledWith({
      contactId: '42',
      tagId: '1',
    });
  });

  it('should show "Add Tag" button', () => {
    render(<ContactTagsEditor contactId='42' />);

    expect(screen.getByTestId('add-tag-button')).toBeInTheDocument();
  });

  it('should open popover with tag list on "Add Tag" click', async () => {
    const user = userEvent.setup();
    render(<ContactTagsEditor contactId='42' />);

    await user.click(screen.getByTestId('add-tag-button'));

    // Should show unassigned tags (Friends, Business) but not already-assigned ones (Work, Family)
    expect(screen.getByTestId('tag-option-3')).toBeInTheDocument();
    expect(screen.getByTestId('tag-option-4')).toBeInTheDocument();
    expect(screen.queryByTestId('tag-option-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('tag-option-2')).not.toBeInTheDocument();
  });

  it('should call assignTagToContact when existing tag is selected', async () => {
    const user = userEvent.setup();
    render(<ContactTagsEditor contactId='42' />);

    await user.click(screen.getByTestId('add-tag-button'));
    await user.click(screen.getByTestId('tag-option-3'));

    expect(mockAssignMutate).toHaveBeenCalledWith({
      contactId: '42',
      tagId: '3',
    });
  });

  it('should show "Create" option when search has no matches', async () => {
    const user = userEvent.setup();
    render(<ContactTagsEditor contactId='42' />);

    await user.click(screen.getByTestId('add-tag-button'));

    const searchInput = screen.getByTestId('tag-search-input');
    await user.type(searchInput, 'NonExistentTag');

    expect(screen.getByTestId('create-tag-option')).toBeInTheDocument();
    expect(screen.getByTestId('create-tag-option')).toHaveTextContent(
      'NonExistentTag'
    );
  });

  it('should show tags section title', () => {
    render(<ContactTagsEditor contactId='42' />);

    expect(screen.getByText('Tags')).toBeInTheDocument();
  });

  it('should show empty state when no tags are assigned', () => {
    mockUseContactTags.mockReturnValue({
      data: createTagListResponse([]),
      isLoading: false,
      isError: false,
    } as any);

    render(<ContactTagsEditor contactId='42' />);

    expect(screen.getByText('No tags assigned')).toBeInTheDocument();
  });

  it('should show loading state when data is loading', () => {
    mockUseContactTags.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    } as any);

    render(<ContactTagsEditor contactId='42' />);

    expect(screen.getByTestId('tags-loading')).toBeInTheDocument();
  });
});
