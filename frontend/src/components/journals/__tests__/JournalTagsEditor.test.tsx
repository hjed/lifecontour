/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { JournalTagsEditor } from '../JournalTagsEditor';
import {
  useJournalTags,
  useAddJournalTag,
  useRemoveJournalTag,
  useCreateJournalTag,
} from '@/lib/api/journals';
import type { JournalTag } from '@/types/journals';

jest.mock('@/lib/api/journals', () => ({
  useJournalTags: jest.fn(),
  useAddJournalTag: jest.fn(),
  useRemoveJournalTag: jest.fn(),
  useCreateJournalTag: jest.fn(),
}));

const mockUseJournalTags = useJournalTags as jest.MockedFunction<
  typeof useJournalTags
>;
const mockUseAddJournalTag = useAddJournalTag as jest.MockedFunction<
  typeof useAddJournalTag
>;
const mockUseRemoveJournalTag = useRemoveJournalTag as jest.MockedFunction<
  typeof useRemoveJournalTag
>;
const mockUseCreateJournalTag = useCreateJournalTag as jest.MockedFunction<
  typeof useCreateJournalTag
>;

const assignedTags: JournalTag[] = [
  { id: 'a', name: 'Work', color: '#3182CE' },
  { id: 'b', name: 'Family', color: '#38A169' },
];

const allTags: JournalTag[] = [
  ...assignedTags,
  { id: 'c', name: 'Friends', color: '#D53F8C' },
  { id: 'd', name: 'Business', color: '#805AD5', parent_id: 'a' }, // child of Work
];

describe('JournalTagsEditor', () => {
  const mockAddMutate = jest.fn();
  const mockAddMutateAsync = jest.fn().mockResolvedValue(undefined);
  const mockRemoveMutate = jest.fn();
  const mockCreateMutateAsync = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();

    mockUseJournalTags.mockReturnValue({
      data: { data: allTags },
      isLoading: false,
      isError: false,
    } as never);

    mockUseAddJournalTag.mockReturnValue({
      mutate: mockAddMutate,
      mutateAsync: mockAddMutateAsync,
      isPending: false,
    } as never);

    mockUseRemoveJournalTag.mockReturnValue({
      mutate: mockRemoveMutate,
      isPending: false,
    } as never);

    mockUseCreateJournalTag.mockReturnValue({
      mutateAsync: mockCreateMutateAsync,
      isPending: false,
    } as never);
  });

  function renderEditor() {
    render(<JournalTagsEditor journalId='j1' assignedTags={assignedTags} />);
  }

  it('renders assigned journal tags as colour-coded badges', () => {
    renderEditor();

    const workBadge = screen.getByTestId('tag-badge-a');
    expect(workBadge).toHaveTextContent('Work');
    expect(workBadge).toHaveStyle({ borderColor: '#3182CE' });
    expect(screen.getByTestId('tag-badge-b')).toHaveTextContent('Family');
  });

  it('lists only unassigned tags in the add popover', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));

    expect(screen.getByTestId('tag-option-c')).toBeInTheDocument();
    expect(screen.getByTestId('tag-option-d')).toHaveTextContent(
      'Work › Business'
    );
    expect(screen.queryByTestId('tag-option-a')).not.toBeInTheDocument();
    expect(screen.queryByTestId('tag-option-b')).not.toBeInTheDocument();
  });

  it('assigns an existing tag on selection', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));
    await user.click(screen.getByTestId('tag-option-c'));

    expect(mockAddMutate).toHaveBeenCalledWith({
      journalId: 'j1',
      tagId: 'c',
    });
  });

  it('removes an assigned tag on X click', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByTestId('remove-tag-a'));

    expect(mockRemoveMutate).toHaveBeenCalledWith({
      journalId: 'j1',
      tagId: 'a',
    });
  });

  it('creates a new tag then assigns it (create-then-assign order)', async () => {
    const user = userEvent.setup();
    mockCreateMutateAsync.mockResolvedValueOnce({ data: { id: 'new-id' } });
    renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));
    await user.type(screen.getByTestId('tag-search-input'), 'Holiday');
    await user.click(screen.getByTestId('create-tag-option'));
    await user.click(screen.getByTestId('colour-#DD6B20'));
    await user.click(screen.getByTestId('confirm-create-tag'));

    await waitFor(() => {
      expect(mockCreateMutateAsync).toHaveBeenCalledWith({
        name: 'Holiday',
        color: '#DD6B20',
      });
    });
    expect(mockAddMutateAsync).toHaveBeenCalledWith({
      journalId: 'j1',
      tagId: 'new-id',
    });
    // create resolved before assign was called
    expect(mockCreateMutateAsync.mock.invocationCallOrder[0]).toBeLessThan(
      mockAddMutateAsync.mock.invocationCallOrder[0]
    );
  });

  it('leaves the create form when the tag was created but assigning it failed', async () => {
    const user = userEvent.setup();
    mockCreateMutateAsync.mockResolvedValueOnce({ data: { id: 'new-id' } });
    mockAddMutateAsync.mockRejectedValueOnce(new Error('Assign failed'));
    renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));
    await user.type(screen.getByTestId('tag-search-input'), 'Holiday');
    await user.click(screen.getByTestId('create-tag-option'));
    await user.click(screen.getByTestId('confirm-create-tag'));

    await waitFor(() => {
      expect(mockAddMutateAsync).toHaveBeenCalled();
    });
    // The tag exists now, so the user must not be stranded on the create form
    // where a retry would re-create the same name and fail.
    await waitFor(() => {
      expect(
        screen.queryByTestId('confirm-create-tag')
      ).not.toBeInTheDocument();
    });
  });

  it('keeps the create form open when creation fails', async () => {
    const user = userEvent.setup();
    mockCreateMutateAsync.mockRejectedValueOnce(new Error('Name exists'));
    renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));
    await user.type(screen.getByTestId('tag-search-input'), 'Holiday');
    await user.click(screen.getByTestId('create-tag-option'));
    await user.click(screen.getByTestId('confirm-create-tag'));

    // Popover create form stays open; assignment never fired
    await waitFor(() => {
      expect(screen.getByTestId('confirm-create-tag')).toBeInTheDocument();
    });
    expect(mockAddMutateAsync).not.toHaveBeenCalled();
  });

  it('shows the loading state while tags load', () => {
    mockUseJournalTags.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    } as never);

    renderEditor();

    expect(screen.getByTestId('tags-loading')).toBeInTheDocument();
  });

  it('shows the error state when the tag list fails to load', () => {
    mockUseJournalTags.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    } as never);

    renderEditor();

    expect(screen.getByTestId('tags-error')).toBeInTheDocument();
  });
});
