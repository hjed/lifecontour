/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { JournalCreateTagDialog } from '../JournalCreateTagDialog';
import { useJournalTags, useCreateJournalTag } from '@/lib/api/journals';
import type { JournalTag } from '@/types/journals';

jest.mock('@/lib/api/journals', () => ({
  useJournalTags: jest.fn(),
  useCreateJournalTag: jest.fn(),
}));

const mockCreateTag = jest.fn();

const EXISTING_TAGS: JournalTag[] = [
  {
    id: '11111111-1111-1111-1111-111111111111',
    name: 'Outdoors',
    color: '#38A169',
    parent_id: null,
  },
];

function renderDialog(onOpenChange = jest.fn()) {
  render(<JournalCreateTagDialog open onOpenChange={onOpenChange} />);
  return { onOpenChange };
}

describe('JournalCreateTagDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCreateTag.mockResolvedValue({ data: { id: 'new-tag' } });
    (useJournalTags as jest.Mock).mockReturnValue({
      data: { data: EXISTING_TAGS },
      isLoading: false,
      error: null,
    });
    (useCreateJournalTag as jest.Mock).mockReturnValue({
      mutateAsync: mockCreateTag,
      isPending: false,
    });
  });

  it('offers the existing journal tags as parents', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByLabelText('Parent Tag'));

    expect(
      await screen.findByRole('option', { name: 'Outdoors' })
    ).toBeInTheDocument();
  });

  it('creates a root-level tag without a parent_id', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();

    await user.type(screen.getByLabelText(/^Name/i), 'Climbing');
    await user.click(screen.getByRole('button', { name: 'Create Tag' }));

    await waitFor(() => {
      expect(mockCreateTag).toHaveBeenCalledWith({
        name: 'Climbing',
        color: '#000000',
      });
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('creates a nested tag with the chosen parent, colour and description', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.type(screen.getByLabelText(/^Name/i), 'Bouldering');
    const colorInput = screen.getByPlaceholderText('#000000');
    await user.clear(colorInput);
    await user.type(colorInput, '#38A169');
    await user.type(screen.getByLabelText(/Description/i), 'Indoor sessions');

    await user.click(screen.getByLabelText('Parent Tag'));
    await user.click(await screen.findByRole('option', { name: 'Outdoors' }));

    await user.click(screen.getByRole('button', { name: 'Create Tag' }));

    await waitFor(() => {
      expect(mockCreateTag).toHaveBeenCalledWith({
        name: 'Bouldering',
        color: '#38A169',
        description: 'Indoor sessions',
        parent_id: EXISTING_TAGS[0].id,
      });
    });
  });

  it('stays open when creation fails so the name can be corrected', async () => {
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
