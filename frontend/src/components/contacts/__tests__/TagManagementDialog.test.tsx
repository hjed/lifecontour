import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TagManagementDialog } from '../TagManagementDialog';
import {
  useUpdateTag,
  useDeleteTag,
  useMergeTag,
  useTags,
} from '@/lib/api/contacts';
import { TagResource } from '@/types/contacts';

// Mock the hooks
jest.mock('@/lib/api/contacts', () => ({
  useUpdateTag: jest.fn(),
  useDeleteTag: jest.fn(),
  useMergeTag: jest.fn(),
  useTags: jest.fn(),
}));

const mockUpdateTag = jest.fn();
const mockDeleteTag = jest.fn();
const mockMergeTag = jest.fn();

const mockTag: TagResource = {
  type: 'tags',
  id: '1',
  attributes: {
    name: 'Friend',
    color: '#ff0000',
    description: 'A close friend',
    created_at: '2023-01-01T00:00:00Z',
    updated_at: '2023-01-01T00:00:00Z',
  },
};

describe('TagManagementDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useUpdateTag as jest.Mock).mockReturnValue({
      mutateAsync: mockUpdateTag,
      isPending: false,
    });
    (useDeleteTag as jest.Mock).mockReturnValue({
      mutateAsync: mockDeleteTag,
      isPending: false,
    });
    (useMergeTag as jest.Mock).mockReturnValue({
      mutateAsync: mockMergeTag,
      isPending: false,
    });
    (useTags as jest.Mock).mockReturnValue({
      data: { data: [] },
      isLoading: false,
    });
  });

  const renderComponent = (props = {}) => {
    return render(
      <TagManagementDialog
        open={true}
        onOpenChange={jest.fn()}
        tag={mockTag}
        {...props}
      />
    );
  };

  it('re-seeds the form when the subject tag changes to one with identical attributes', async () => {
    // The dialog stays mounted, so the form is only re-seeded when
    // `initialValues` changes identity. Keying that memo on attributes alone
    // would leak a draft into a different tag's edit.
    const user = userEvent.setup();
    const { rerender } = renderComponent();

    await user.clear(screen.getByLabelText(/Name/i));
    await user.type(screen.getByLabelText(/Name/i), 'Half typed');

    const twinTag: TagResource = { ...mockTag, id: '99' };
    rerender(
      <TagManagementDialog open onOpenChange={jest.fn()} tag={twinTag} />
    );

    expect(screen.getByLabelText(/Name/i)).toHaveValue('Friend');
  });

  it('renders correctly with tag details', () => {
    renderComponent();

    expect(
      screen.getByRole('dialog', { name: 'Edit Tag' })
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Name/i)).toHaveValue('Friend');
    expect(screen.getByLabelText(/Description/i)).toHaveValue('A close friend');
    expect(screen.getByPlaceholderText('#000000')).toHaveValue('#ff0000');
  });

  it('calls update function when form is saved', async () => {
    renderComponent();
    const user = userEvent.setup();

    const nameInput = screen.getByLabelText(/Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Best Friend');

    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(mockUpdateTag).toHaveBeenCalledWith({
        id: '1',
        attributes: {
          name: 'Best Friend',
          color: '#ff0000',
          description: 'A close friend',
          parent_id: null,
        },
      });
    });
  });

  it('calls delete function when delete is confirmed', async () => {
    const onOpenChange = jest.fn();
    renderComponent({ onOpenChange });
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'Delete Tag' }));

    // Alert dialog should appear
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
    expect(screen.getByText('Are you absolutely sure?')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(mockDeleteTag).toHaveBeenCalledWith('1');
    });

    // Should close dialog after delete
    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it('validates required fields', async () => {
    renderComponent();
    const user = userEvent.setup();

    const nameInput = screen.getByLabelText(/Name/i);
    await user.clear(nameInput);

    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    // Note: Depends on how Zod validation messages show up
    expect(await screen.findByText('Name is required')).toBeInTheDocument();
    expect(mockUpdateTag).not.toHaveBeenCalled();
  });

  // The suite above mocks an empty tag list, which leaves the parent and merge
  // dropdowns with nothing to render. These populate it so both selects are
  // actually exercised.
  describe('with other tags available', () => {
    const otherTags: TagResource[] = [
      mockTag,
      {
        type: 'tags',
        id: '2',
        attributes: {
          name: 'Colleague',
          created_at: '2023-01-01T00:00:00Z',
          updated_at: '2023-01-01T00:00:00Z',
        },
      },
    ];

    beforeEach(() => {
      (useTags as jest.Mock).mockReturnValue({
        data: { data: otherTags },
        isLoading: false,
      });
    });

    it('excludes the edited tag from the parent options', async () => {
      renderComponent();
      const user = userEvent.setup();

      await user.click(screen.getByLabelText('Parent Tag'));

      expect(
        await screen.findByRole('option', { name: 'Colleague' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('option', { name: 'None (Root Level)' })
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('option', { name: 'Friend' })
      ).not.toBeInTheDocument();
    });

    it('re-parents the tag to the selected parent', async () => {
      renderComponent();
      const user = userEvent.setup();

      await user.click(screen.getByLabelText('Parent Tag'));
      await user.click(
        await screen.findByRole('option', { name: 'Colleague' })
      );
      await user.click(screen.getByRole('button', { name: 'Save Changes' }));

      await waitFor(() => {
        expect(mockUpdateTag).toHaveBeenCalledWith(
          expect.objectContaining({
            attributes: expect.objectContaining({ parent_id: 2 }),
          })
        );
      });
    });

    it('merges into the selected target after confirmation', async () => {
      const onOpenChange = jest.fn();
      renderComponent({ onOpenChange });
      const user = userEvent.setup();

      const mergeButton = screen.getByRole('button', { name: 'Merge' });
      expect(mergeButton).toBeDisabled();

      await user.click(screen.getByLabelText('Merge into'));
      await user.click(
        await screen.findByRole('option', { name: 'Colleague' })
      );
      await user.click(screen.getByRole('button', { name: 'Merge' }));

      await user.click(screen.getByRole('button', { name: 'Confirm Merge' }));

      await waitFor(() => {
        expect(mockMergeTag).toHaveBeenCalledWith({
          sourceId: '1',
          targetId: '2',
        });
      });
      await waitFor(() => {
        expect(onOpenChange).toHaveBeenCalledWith(false);
      });
    });
  });
});
