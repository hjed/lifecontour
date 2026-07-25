/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { CreateTagDialog } from '../CreateTagDialog';
import { useCreateTag } from '@/lib/api/contacts';

jest.mock('@/lib/api/contacts', () => ({
  useCreateTag: jest.fn(),
}));

const mockCreateTag = jest.fn();

function renderDialog(props: { parentId?: number } = {}) {
  const onOpenChange = jest.fn();
  render(<CreateTagDialog open onOpenChange={onOpenChange} {...props} />);
  return { onOpenChange };
}

describe('CreateTagDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCreateTag.mockResolvedValue({});
    (useCreateTag as jest.Mock).mockReturnValue({
      mutateAsync: mockCreateTag,
      isPending: false,
    });
  });

  it('renders an empty form with the default colour', () => {
    renderDialog();

    expect(
      screen.getByRole('dialog', { name: 'Create Tag' })
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/i)).toHaveValue('');
    expect(screen.getByPlaceholderText('#000000')).toHaveValue('#000000');
  });

  it('offers no parent field — contacts create tags at the root', () => {
    renderDialog();

    expect(screen.queryByLabelText('Parent Tag')).not.toBeInTheDocument();
  });

  it('creates the tag and closes', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();

    await user.type(screen.getByLabelText(/^Name/i), 'Colleague');
    await user.type(screen.getByLabelText(/Description/i), 'Works with me');
    await user.click(screen.getByRole('button', { name: 'Create Tag' }));

    await waitFor(() => {
      expect(mockCreateTag).toHaveBeenCalledWith({
        name: 'Colleague',
        color: '#000000',
        description: 'Works with me',
        parent_id: undefined,
      });
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('passes an explicit parentId through when the caller supplies one', async () => {
    const user = userEvent.setup();
    renderDialog({ parentId: 7 });

    await user.type(screen.getByLabelText(/^Name/i), 'Nested');
    await user.click(screen.getByRole('button', { name: 'Create Tag' }));

    await waitFor(() => {
      expect(mockCreateTag).toHaveBeenCalledWith(
        expect.objectContaining({ parent_id: 7 })
      );
    });
  });

  it('requires a name', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'Create Tag' }));

    expect(await screen.findByText('Name is required')).toBeInTheDocument();
    expect(mockCreateTag).not.toHaveBeenCalled();
  });

  it('stays open when creation fails', async () => {
    const user = userEvent.setup();
    mockCreateTag.mockRejectedValueOnce(new Error('Name already exists'));
    const { onOpenChange } = renderDialog();

    await user.type(screen.getByLabelText(/^Name/i), 'Duplicate');
    await user.click(screen.getByRole('button', { name: 'Create Tag' }));

    await waitFor(() => {
      expect(mockCreateTag).toHaveBeenCalled();
    });
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
