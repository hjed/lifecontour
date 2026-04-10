import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TagManagementDialog } from '../TagManagementDialog';
import { useUpdateTag, useDeleteTag } from '@/lib/api/contacts';
import { TagResource } from '@/types/contacts';

// Mock the hooks
jest.mock('@/lib/api/contacts', () => ({
  useUpdateTag: jest.fn(),
  useDeleteTag: jest.fn(),
}));

const mockUpdateTag = jest.fn();
const mockDeleteTag = jest.fn();

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
});
